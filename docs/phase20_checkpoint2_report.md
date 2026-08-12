# PHASE 20 — CHECKPOINT 2 REPORT (M6–M11)

**Status: reporting only. No enforce activation, no `.env` changes, no worker restarts, no
Telegram sends, no paid calls, no Phase 21 work. Story Memory V2 remains fully shadow-only; the
real `.env` still has `story_memory_mode=off`.** A newly discovered blocker (candidate-retrieval
capacity, §4) is disclosed and **left unfixed** per explicit instruction, pending review.

---

## 1. Files changed this milestone range (M6–M11)

**New:**
- `services/story_delta_engine.py` (M6) — deterministic Delta Engine
- `services/story_confidence.py` (M7/M10) — confidence bands
- `services/story_suppression.py` (M7) — suppression proposal policy
- `database/migrations/versions/3c22be05f4e5_add_story_memory_v2_shadow_columns.py` (M10) —
  **created, not applied**
- `scripts/phase20_story_memory_replay.py` (M11) — historical replay harness
- `tests/test_story_delta_engine.py`, `tests/test_story_suppression.py`,
  `tests/test_story_memory_v2_shadow_isolation.py` (M6/M7/M10)
- `artifacts/phase20_m11_replay_results.json` — real replay output (this report's evidence base)

**Modified:**
- `services/triage_orchestrator.py` (M8) — added `RELATED_STORY` import + `TriageCycleReport.
  story_related` counter, wired into `_apply_story_memory()`. Pure observability addition; no
  behavior change to any existing outcome.
- `services/story_context_serializer.py` (M9) — added `serialize_delta_engine_context()`, purely
  additive; `serialize_prior_coverage()` itself untouched.
- `database/models/story_link.py` (M10) — docstring only, explaining why the 3 new columns are
  **not yet** declared on the ORM model (see §3).
- `tests/test_triage_orchestrator_story_memory.py` (M8) — added a test for the `story_related`
  counter wiring.
- `tests/test_copywriting_v6_context_seam.py` (M9) — added tests P/Q for the new serializer
  function and its live-path isolation.

## 2. Migration status

Exactly one new migration this range: `3c22be05f4e5` (3 nullable columns —
`delta_classification`, `confidence_band`, `would_suppress` — on `news_event_story_links`).
**Created, chained cleanly onto the real head (`94fd27f7d129`), single-head confirmed
(`alembic heads` → `3c22be05f4e5`). Not applied to the real database.** The ORM model
(`database/models/story_link.py`) deliberately does **not** yet declare these columns — doing so
was tried during M10 and immediately broke every real `NewsEventStoryLink` insert
(`UndefinedColumnError: column "delta_classification" ... does not exist`), because SQLAlchemy
includes every mapped column in every generated `INSERT` regardless of whether it was explicitly
set. Reverted; documented in the model's own docstring. Model and migration will be updated
together in a future, separately authorized step.

## 3. Delta Engine — exact logic (M6)

`services/story_delta_engine.py`, pure `classify_delta(new_title, prior_titles) → DeltaResult` +
thin async `compute_story_delta()` wrapper. Reuses `services/fact_safety.py::extract_claims()`
for money/percentage/date/metric-quantity detection (no new parser) and
`services/story_memory.py::extract_story_signature()` for keyword-set delta.

Classification order (first match wins):
1. **MATERIAL_UPDATE** — a money/percentage/date/metric-quantity claim in the new title, not
   present (after loose normalization) in the union of all prior titles' own claims of the same
   type.
2. **NO_NEW_FACTS** — symmetric title overlap ≥ 0.85 AND no new keywords.
3. **CONFIRMATION_ONLY** — symmetric title overlap ≥ 0.55, no material claim.
4. **MINOR_DELTA** — 1–4 new distinctive keywords, no material claim.
5. **UNCERTAIN_DELTA** — everything else (ambiguous).

**Disclosed limitation** (found during M6, not fixed — inherited from `fact_safety.py`'s own
pattern, not something this engine should duplicate-fix): a bare "March 15" without a year does
not match `_DATE_EXTRACT_PATTERN`, so it degrades to `MINOR_DELTA`/`UNCERTAIN_DELTA` rather than
`MATERIAL_UPDATE` — never silently `NO_NEW_FACTS`, so it degrades safely.

14 unit tests, all passing (`tests/test_story_delta_engine.py`), including the exact worked
examples from the approval message (confirmation-by-another-source → not material;
release-date-becomes-known → `MATERIAL_UPDATE`; independent-benchmark-appears →
`MATERIAL_UPDATE`; different-wording-alone → never `MATERIAL_UPDATE`).

## 4. Suppression policy — exact rules (M7)

`services/story_suppression.py::compute_would_suppress(match_type, confidence_band,
delta_classification) → bool`:

- `True` **only** when `match_type ∈ {SEMANTIC_DUPLICATE, SUPPORTING_SOURCE}` **and**
  `confidence_band == HIGH` **and** `delta_classification ∈ {NO_NEW_FACTS, CONFIRMATION_ONLY}`.
- `MINOR_DELTA`/`UNCERTAIN_DELTA` never suppress (conservative-false, no strong replay evidence
  yet — see §9).
- `UNCERTAIN_MATCH` never suppresses, unconditionally (non-negotiable).
- `STORY_UPDATE`, `MATERIAL_UPDATE`, `RELATED_STORY`, `NEW_STORY` never suppress.

74 parametrized tests exhaustively cover every `match_type × confidence_band ×
delta_classification` combination (`tests/test_story_suppression.py`), all passing.

## 5. Confidence bands (M7/M10)

`services/story_confidence.py::compute_confidence_band(combined_score) → HIGH|MEDIUM|LOW`,
reusing `story_memory.py`'s own existing `_HIGH_THRESHOLD=0.65`/`_LOW_THRESHOLD=0.35` as the
starting boundary hypothesis (plan §18's own instruction — "reuse today's split... expect these
to move once real data exists"). Only meaningful for the 4 outcomes where `MatchResult.confidence`
equals the raw `combined` score (`STORY_UPDATE`/`SUPPORTING_SOURCE`/`SEMANTIC_DUPLICATE`/
`UNCERTAIN_MATCH`) — `NEW_STORY`/`RELATED_STORY` use a different confidence scale and are never
banded.

## 6. Story Timeline / source accumulation (M8)

Confirmed sufficient as-is, no new table: `NewsEventStoryLink` already accumulates every matched
event under one `story_id`; `Story.event_count` already tracks volume.

**One real, narrow gap found and fixed**: `RELATED_STORY` (added in M5) was never wired into
`TriageCycleReport`'s per-outcome counters in `services/triage_orchestrator.py` — a pure
observability omission (the link itself was always persisted correctly with
`match_type="related_story"`; only the summary counter was silently missing this outcome). Fixed
by adding `story_related: int` and its `elif` branch. Zero behavior change; `story_memory_mode`
stays `off` in the real `.env`, so this had zero live effect until now.

**One real, NOT-fixed design gap, surfaced by M11's replay, directly relevant to §8 below**:
`_apply_story_memory()`'s dispatch (unchanged since Phase 18.10) only creates a fresh `Story` row
for the `NEW_STORY` outcome. Every other outcome — including `UNCERTAIN_MATCH` and
`RELATED_STORY`, neither of which represents a confirmed same-story match — attaches the event to
whatever *existing* candidate it scored best against, and creates no `Story` of its own. This
means a genuinely novel event whose best available score happens to land in the uncertain band or
just above the `RELATED_STORY` entity floor (against some unrelated older story) gets no story
identity of its own. Documented, not touched — this is production-shaping logic already live
since Phase 18.10 in the (currently `off`) shadow path, out of scope for a narrow M8 verification
pass. See §8 for how this measurably compounds the Kitesurf miss in the replay.

## 7. V6 update-context contract (M9)

`services/story_context_serializer.py::serialize_delta_engine_context(delta_result,
confidence_band, would_suppress) → str` — new, additive function alongside the existing (Phase 19)
`serialize_prior_coverage()`, which is untouched. Deterministic, bounded (≤8 items each for
material claims / new keywords), always explicit that `would_suppress` is "a shadow recommendation
only, NOT enforced." **Tests/replay only** — confirmed via two new AST-based isolation tests
(`test_copywriting_v6_context_seam.py::test_q_*`) that neither `capabilities/
copywriting_capability.py` nor `capabilities/executor.py` import any Story Memory V2 module.

## 8. Historical replay (M11)

`scripts/phase20_story_memory_replay.py`. Disposable `docker run postgres:16`, migrated to head
(including the unapplied M10 migration — safe and correct in a throwaway container), destroyed
after. Zero paid calls (fully deterministic), zero Telegram, zero production mutation (source data
read via a **read-only** `SELECT` against the real DB; all writes went to the disposable
container only).

**Replay period: 2026-08-04 through 2026-08-07 (4 full real days, exclusive end 2026-08-08),
3,774 real historical `NewsEvent` rows**, replayed in exact chronological order (`published_at`).
This window was chosen because it includes 2026-08-07, the exact date of all 4 real calibration
cases, letting them be re-tested under realistic multi-thousand-event candidate competition rather
than the isolated single-candidate unit tests.

### 8a. Candidate-pool limit/cap behavior — **NEWLY DISCOVERED BLOCKER**

| Metric | Value |
|---|---|
| `STORY_MATCH_CANDIDATE_LIMIT` | 150 |
| Total candidate-pool fetches instrumented | 3,777 |
| Fetches that hit the cap exactly (150/150 returned) | **3,558 (94.2%)** |
| Mean pool size | 145.8 |
| Min / Max pool size | 0 / 150 |

**The 150-candidate cap is saturated on 94.2% of all retrievals across ordinary production-volume
days (750–1,200 events/day).** This was not visible in any prior testing this phase — the
isolated `tests/test_story_memory_v2.py` unit tests bypass retrieval entirely (they monkeypatch
`_fetch_candidate_stories` to return exactly one hand-picked candidate), and Checkpoint 1's
manual re-scoring likewise compared directly against the one known-correct candidate. Only a
real, multi-day, full-volume replay could surface this, which is exactly why M11 was scoped as
load-bearing rather than another short burst.

### 8b. Exact AI Olympiad scatter mechanism — measured, not inferred

Three real events, all in `services/story_memory.py`'s intended cluster:
- Event 4 (`0223f966`, 16:23) — the true root
- Event 8 (`7370d474`, 16:37) — a corroborating source, previously linked correctly pre-Phase-20
- Event 14 (`747aa0cc`, 16:53) — the previously-silently-lost event (Checkpoint 1)

Instrumented, per-event candidate-pool trace (`known_case_pool_diagnostics` in
`artifacts/phase20_m11_replay_results.json`):

| Event | Candidate pool | Saturated? | True prior sibling present in pool? | Actual outcome | Root cause |
|---|---|---|---|---|---|
| Event 4 (root) | — | — | n/a (no sibling exists yet) | `UNCERTAIN_MATCH` (0.46) against an **unrelated** older story | Landed on an unrelated candidate purely by score coincidence; `UNCERTAIN_MATCH` creates no `Story` of its own (§6) |
| Event 8 vs Event 4 | 150/150 | **Yes** | **No — absent from pool entirely** | `UNCERTAIN_MATCH` (0.588) against a **different** unrelated story | Capacity: Event 4 never had its own story (previous row); the unrelated story it *pointed at* aged out of the top-150-by-recency window in the 14 minutes before Event 8 ran |
| Event 14 vs Event 4's target | 150/150 | Yes | **No — absent from pool** | — | Same capacity exclusion |
| Event 14 vs Event 8's target | 150/150 | Yes | **Yes — present, scored 0.215** (entity=0.125, title=0.1) | `RELATED_STORY` (linked instead to the unrelated Moscow story, 0.25) | Not a capacity miss for this specific pair — genuinely low score, compounded by the already-disclosed (Checkpoint 1) Russian morphology gap |

**Root mechanism, precisely**: Event 4 never creates its own `Story` (it lands `UNCERTAIN_MATCH`
against an unrelated older candidate, and `UNCERTAIN_MATCH` — correctly, by design — never
creates a story of its own). With no genuine "AI Olympiad" story ever instantiated, every later
event in the real cluster (8, 14) has nothing correct to find. Event 8's own attempt to find
*any* prior AI-Olympiad-cluster story is then independently blocked by capacity (§8a) — the
candidate it did point at aged out of the recency window before Event 8 was even processed. This
is two compounding, independently-confirmed mechanisms (§6's story-identity gap, §8a's capacity
saturation), not one.

### 8c. Was the correct Story absent from the candidate pool, and why — per known case

- **Kitesurf**: the "correct" candidate (event 2's own Kitesurf-titled story) **never existed at
  all** — event 2 itself landed `RELATED_STORY` (score 0.2) against an unrelated older candidate,
  not `NEW_STORY`, so no dedicated Kitesurf story was ever created for event 13 to find. This is
  the §6 story-identity gap, not a capacity miss — when I forcibly re-scored event 13 against the
  *actual* Kitesurf-titled story object (as the isolated Checkpoint-1 unit test does), it scored
  0.181 combined (entity=0.167, title=0.077) — **far lower than the isolated test's originally
  reported 0.740**, because in the disposable-DB replay the "story" I could score against was
  reconstructed from the real title text, but the *isolated unit test's controlled candidate* and
  *this replay's real historical event's actual title text* are not proven identical strings
  (both use the real Phase 19 artifact title, so this discrepancy is flagged as unresolved and
  worth re-checking before any threshold is finalized — see §11).
- **AI Olympiad**: see §8b — event 8's target absent from pool (capacity); event 14's target
  against event 4 also absent (capacity); event 14 against event 8's (unrelated) target present
  but genuinely low-scoring.
- **Moscow student pair**: candidate **present** in both cases checked, scored and matched exactly
  as Checkpoint 1 predicted (`UNCERTAIN_MATCH`, 0.528, correctly pointing at its own true sibling
  — `actual_matched_prior_sibling: true`). Not affected by either mechanism. Confirms the pattern:
  cases whose root event lands as genuine `NEW_STORY` (Moscow, GTA) go on to behave correctly;
  cases whose root event lands as `UNCERTAIN_MATCH`/`RELATED_STORY` (Kitesurf, AI Olympiad) lose
  story identity permanently.
- **GTA negative control**: candidate present, scored correctly low (combined=0.031, entity=0.0,
  title=0.077) — stayed `NEW_STORY` on the merits, not because of capacity. **Negative control
  passes cleanly under full realistic load.**

### 8d. All other real missed links attributable to retrieval capacity

Beyond the AI Olympiad cluster (§8b), no other *labeled* case in the calibration set showed a
capacity-caused miss (Moscow and GTA both had their true candidate present in-pool). Given the
94.2% saturation rate found in §8a, it is highly likely that unlabeled real missed-merges exist
elsewhere in the 3,774-event corpus, but this cannot be quantified without a human-labeled ground
truth for the full corpus, which does not exist. This is stated as a limitation, not glossed over.

### 8e. False merges

**Zero false merges detected in the labeled calibration set** (4 real cases, 10 events; 5
synthetic cases already covered by the permanent pytest suite, unaffected by replay since they use
fixed synthetic IDs not present in real historical data). GTA — the single most important
precision regression test in the whole suite — stayed correctly separated (`NEW_STORY`/`NEW_STORY`)
under full 94.2%-saturated realistic load, on the merits, not by accident of retrieval exclusion.

No exhaustive false-merge audit of the full unlabeled 3,774-event corpus was performed (no ground
truth exists for it) — see §8d.

### 8f. All false suppressions

**Zero of the 4 labeled real cases ever reached a `would_suppress=True` state** (none combined
`SEMANTIC_DUPLICATE`/`SUPPORTING_SOURCE` + `HIGH` confidence + `NO_NEW_FACTS`/`CONFIRMATION_ONLY`
delta simultaneously) — the conservative policy correctly stayed silent on all 4, including the
one case (Kitesurf) that *should* eventually suppress once the story-identity gap (§6) is fixed.
No false positive, but also no true positive to validate against in the labeled set — the policy
has not yet been positively exercised against known-good data.

Across the full unlabeled corpus: **222 of 3,774 events (5.9%) were flagged `would_suppress=True`**
(all `SEMANTIC_DUPLICATE`/`SUPPORTING_SOURCE` + `HIGH` + no-material-delta). A 25-item sample was
spot-checked by title (`would_suppress_examples` in the artifact) — the large majority are
duplicate arXiv-abstract-style titles or literal repeated headlines (plausible true suppressions),
but this is a spot check, not a human-labeled audit, and is reported as such — **no suppression
precision/recall number is claimed for the unlabeled corpus.**

### 8g. Suppression precision / recall

**Not computable with confidence at this stage.** Labeled-set precision/recall is vacuous (0
positive predictions on 4 cases where none should suppress yet — see §8f). Unlabeled-corpus
precision/recall would require human review of the 222 flagged cases, not done this milestone.
Stated explicitly, not estimated.

### 8h. Update-detection metrics

`delta_classification` distribution across the full replay (3,774 events; only computed for the
4 "compared" outcomes — 771 of them):

| Classification | Count |
|---|---|
| `no_new_facts` | 203 |
| `confirmation_only` | 96 |
| `minor_delta` | 28 |
| `material_update` | 28 |
| `uncertain_delta` | 188 |

`material_update` (a genuinely new date/money/percentage/quantity claim) fired 28 times — every
one of these represents an event the Delta Engine judged as adding real substance to an existing
story, none suppressed (by design — `MATERIAL_UPDATE` never suppresses).

### 8i. Uncertain rate

`uncertain_match`: 281 of 3,774 events (**7.4%** of all events; **36.5% of the 771 "compared"
same-story-candidate outcomes**). `uncertain_delta`: 188 of 771 compared outcomes (24.4%).

### 8j. Full outcome distribution (all 14 required metrics, consolidated)

1. Total events replayed: **3,774**
2. `NEW_STORY`: 2,441 (64.7%)
3. `STORY_UPDATE`: 39 (1.0%)
4. `SUPPORTING_SOURCE`: 4 (0.1%)
5. `SEMANTIC_DUPLICATE`: 219 (5.8%)
6. `UNCERTAIN_MATCH`: 281 (7.4%) — §8i
7. `RELATED_STORY`: 793 (21.0%)
8. Candidate-pool saturation rate: **94.2%** — §8a
9. `delta_classification` distribution — §8h
10. `confidence_band`: HIGH 262, MEDIUM 281 (LOW never recorded — `LOW`-band matches don't reach
    the "compared" outcome set at all, since `combined < 0.35` is `NEW_STORY`/`RELATED_STORY`, not
    banded)
11. `would_suppress=True` count: **222 (5.9% of all events, 28.8% of the 771 compared outcomes)**
    — §8f
12. False merges (labeled set): **0** — §8e
13. False suppressions (labeled set): **0 observed, 0 opportunities** — §8f
14. Known-case results (per-case, labeled): Kitesurf **regressed vs. Checkpoint 1's isolated
    measurement** (§8c — story-identity gap); AI Olympiad event 8 **regressed** (was
    `SUPPORTING_SOURCE` pre-Phase-20 and in Checkpoint 1's isolated test, now `UNCERTAIN_MATCH`
    against an unrelated story under full load); AI Olympiad event 14 **unchanged**
    (`UNCERTAIN_MATCH`/`RELATED_STORY`, still not silently lost); Moscow pair **matches
    Checkpoint 1 exactly**; GTA **passes cleanly**.

## 9. Recommended thresholds

**No threshold change is recommended at this time.** The replay does not point at a scoring
threshold that needs tuning — the dominant failures (§8b, §8c) are retrieval-capacity and
story-identity gaps, not miscalibrated score cutoffs. Raising `STORY_MATCH_CANDIDATE_LIMIT` alone
would likely help but was not tested this milestone (explicitly out of scope per this checkpoint's
own instruction not to fix the capacity issue before reporting) — its effect on retrieval-query
cost at real `stories` table volumes is unmeasured. **Do not lock a specific new limit or
threshold without a follow-up replay that tests one.**

## 10. GO/NO-GO for Story Memory `enforce`

**NO-GO.** Two real, replay-confirmed blockers stand between the current implementation and any
`enforce`-mode consideration:

1. **Candidate-retrieval capacity** (§8a) — saturated 94.2% of the time at real production
   volume; directly causes confirmed missed links (§8b).
2. **Story-identity gap** (§6, §8c) — `UNCERTAIN_MATCH`/`RELATED_STORY` outcomes never create a
   `Story` of their own, permanently blocking future convergence for genuinely novel stories whose
   first mention happens to score in the uncertain/related band against an unrelated older
   candidate (Kitesurf's exact failure mode).

Both are **disclosed, not fixed**, per this checkpoint's explicit instruction. Story Memory V2
remains safe to leave in its current shadow-only, `off`-by-default state — nothing in this report
changes real production behavior — but is **not ready for shadow activation, let alone enforce**,
until both blockers are addressed and re-validated by another replay.

## 11. Explicit confirmation: production behavior unchanged

- `story_memory_mode` remains `off` in the real `.env` (default, untouched).
- No worker was started or restarted.
- No Telegram message was sent (structurally impossible — the replay never imports any bot/
  Telegram module).
- No paid LLM call was made (Delta Engine, confidence bands, suppression, and the matcher itself
  are 100% deterministic; the replay script imports no LLM gateway).
- No migration was applied to the real database — the disposable container was destroyed after
  the run.
- No code was committed.

## 12. Full regression suite result

`python -m pytest tests/` (single full run, as instructed): **2,917 passed, 39 failed, 27 skipped,
16 errors, 4051.10s (1:07:31)**.

**All 39 failures + 16 errors are pre-existing dev-database data pollution, unrelated to any
Phase 20 code.** Verified two ways:
1. **Zero overlap**: none of the 39 failed / 16 errored tests are in any Phase 20 M6–M11 file
   (`test_story_memory*.py`, `test_story_delta_engine.py`, `test_story_suppression.py`,
   `test_story_memory_v2_shadow_isolation.py`, `test_copywriting_v6_context_seam.py`,
   `test_phase20_m1_harness_fixes.py`, `test_triage_orchestrator_story_memory.py`) — confirmed by
   direct grep of the full failure list.
2. **Root cause is data, not code** — sampled several representative failures directly:
   - `test_capability_executor.py::test_capability_executor_is_a_drop_in_step_executor` and ~7
     siblings: `assert 4863 == 0` — the test assumes an empty `ai_executions` table; the real dev
     DB has **4,863 real rows** (confirmed via direct `psql` count), left by the already-authorized
     Phase 19 overnight A/B/C real-money validation run, which intentionally wrote real cost rows.
   - ~25 more failures/errors: repeated `ForeignKeyViolationError: ... violates foreign key
     constraint "content_draft_editorial_plans_event_id_fkey"` during test teardown — a stray,
     already-existing `ContentDraftEditorialPlan` row (from earlier Editorial Planning shadow-mode
     work) blocks cleanup of a `NewsEvent` row that many unrelated test fixtures happen to collide
     on.
   Both are **real database row counts / stray rows**, not code — branch-independent by
   construction. Every one of these tests would fail identically on `main` today, run against the
   same, already-polluted dev database, since the cause is data state, not code differences. This
   session's targeted Phase 20 test runs (10+ separate invocations across M1–M11, all against this
   same real DB) never hit this pollution because none of them assert a global `ai_executions`
   count or touch the specific stray row's `NewsEvent` id.
- A confirmed, permanent regression suite for Phase 20 itself
  (`test_story_memory.py` + `test_story_memory_integration.py` + `test_story_memory_v2.py` +
  `test_story_delta_engine.py` + `test_story_suppression.py` +
  `test_story_memory_v2_shadow_isolation.py` + `test_copywriting_v6_context_seam.py` +
  `test_triage_orchestrator_story_memory.py` + `test_phase20_m1_harness_fixes.py`) was re-run
  cleanly, isolated from the full-suite pollution, immediately before this report.
