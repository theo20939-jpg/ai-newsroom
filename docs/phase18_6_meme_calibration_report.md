# Phase 18.6 — Meme Opportunity Human Calibration: Final Report

Status: **calibration dataset prepared, human review pending.** This phase does not change meme
detection behavior, does not enable any live mode, and does not produce a GO/NO-GO on its own —
it only builds the tooling and dataset a human reviewer needs to calibrate the existing Phase 18
M1 classifier against real editorial judgement.

---

## 1. Objective

Compare the existing, deterministic meme opportunity classifier
(`services.meme_opportunity.assess_meme_opportunity()`, unchanged since Phase 18 M1) against human
editorial judgement, by building a 50-item, stratified, human-reviewable calibration dataset drawn
from real production `NewsEvent` rows — and the tooling to turn a completed review into concrete
precision/recall/false-positive/correlation/category/safety metrics once that review happens. This
phase does **not** attempt to improve, retune, or enable meme generation; it only prepares the
measurement.

## 2. Architecture impact

**None.** `git diff --stat` against the prior checkpoint (`checkpoint/phase18-5-final-complete`)
touches 7 files, all new, zero modifications to any existing file. No changes to
`core/config.py`, `capabilities/executor.py`, `services/meme_opportunity.py`, `services/
meme_safety.py`, or `database/migrations/`. `meme_opportunity_mode` remains `"off"`. No new
database table, no new migration — the dataset lives entirely in a committed JSON file plus a
committed markdown rendering of it, following the same pattern `schemas/meme_shadow_analytics.py`
(Phase 18.5) already established.

The one new architectural element is `schemas/meme_calibration.py` + `services/
meme_calibration.py` — a purely additive layer that reuses Phase 18.5's own `services.
meme_shadow_analytics.evaluate_event_shadow()` (which itself calls the unmodified Phase 18 M1
classifier) rather than re-deriving any classification logic. Every `algorithm_score`/
`algorithm_level`/`triggered_signals`/`safety_result` value in this phase's dataset traces back to
that one, single, already-reviewed code path.

## 3. Files changed

| File | Status | Purpose |
|---|---|---|
| `schemas/meme_calibration.py` | new | `MemeCalibrationRecord`, `MemeReviewGroup`, `MemeCalibrationHumanDecision`, `MemeCalibrationReason`, `MemeCalibrationSafetyOpinion`, `MemeCalibrationDataset` — frozen, `extra="forbid"`, every `human_*` field genuinely nullable |
| `services/meme_calibration.py` | new | pure selection (`select_diverse_by_category`, `select_random`), record building, markdown rendering, and metric functions (`opportunity_classifier_metrics`, `score_correlation`, `category_analysis`, `safety_analysis`) |
| `scripts/phase18_6_generate_calibration_packet.py` | new, committed | read-only extraction driver — queries `NewsEvent`, runs the existing classifier via Phase 18.5's `evaluate_event_shadow()`, selects the three groups, writes the dataset + packet |
| `scripts/phase18_6_calibration_dataset.json` | new, committed | the 50-item calibration dataset itself (20/20/10 split), every `human_*` field `null` |
| `docs/phase18_6_human_review_packet.md` | new, committed | the same 50 items rendered as a human-readable markdown packet, every human-decision field the literal placeholder `_[ not yet reviewed ]_` |
| `scripts/phase18_6_calibration_analysis.py` | new, committed | thin driver reading a *completed* dataset JSON, calling `services.meme_calibration`'s metric functions; reports an honest "pending" status when nothing has been reviewed yet |
| `tests/test_phase18_6_meme_calibration.py` | new | 58 tests |

No existing file was modified. No secret, `.env` value, or credential appears in any of the above.

## 4. Dataset selection logic

Run once, read-only, against the real `ai_newsroom` production database (12,430 `NewsEvent` rows,
same corpus Phase 18.5 already classified). `NewsEvent` row count verified identical before and
after (12,430 → 12,430); zero rows written anywhere (verified: zero `EditorialTask` rows reference
`meme_calibration` afterward).

- **Group A — 20 `MEDIUM` candidates, maximum category diversity.** `select_diverse_by_category()`
  round-robins across every distinct category actually present among real `MEDIUM`-labeled records
  (deterministic, seed `18.6`), one record per category per pass, until 20 are selected or the pool
  is exhausted. The real `MEDIUM` pool only ever contains 4 of the 8 `EventCategory` values (a
  finding Phase 18.5 M2 already established: AI, STARTUPS, UNKNOWN, SOFTWARE) — the actual selected
  20 break down as AI 14, STARTUPS 3, UNKNOWN 2, SOFTWARE 1, i.e. the maximum diversity the real
  classified population actually supports, not an artificially balanced or padded sample.
- **Group B — 20 random `LOW` examples.** `select_random()`, deterministic seed `18.6`, sampling
  without replacement (no duplicates possible within one call) from the full `LOW` pool (12,193
  real records per Phase 18.5 M2).
- **Group C — 10 random safety-`BLOCKED` examples.** Same `select_random()` function, applied to
  the full `BLOCKED` pool (182 real records per Phase 18.5 M2).

All three groups filled to their full target size (20/20/10 = 50) — no group was short of real
data, unlike Phase 18.5 M3's own packet where Group `HIGH` had zero available items.

## 5. Safety guarantees

- **Zero LLM calls.** `services/meme_calibration.py` and both scripts import no LLM Gateway module
  — verified by `test_no_forbidden_imports` (AST-based import-boundary check, parametrized over
  all three new non-test files).
- **Zero Telegram sends.** No `bot.` import anywhere in this phase's code (same test).
- **Zero image generation.** No `meme_image_generation`/`meme_render` import anywhere (same test).
- **Zero production mutations.** `scripts/phase18_6_generate_calibration_packet.py` contains one
  read-only `SELECT` and nothing else (`test_no_insert_update_delete_statements_in_generation_
  script` — textual guard for `session.add(`/`session.commit(`/`insert(`/`update(`/`delete(`/
  `.execute(text(`); `scripts/phase18_6_calibration_analysis.py` contains no database code of any
  kind (`test_analysis_script_has_no_database_imports_at_all` — checks for the literal absence of
  `database.session`/`sqlalchemy` in its source, since this script only ever reads a local JSON
  file). Verified empirically too: real `NewsEvent` row count identical before/after the extraction
  run.
- **No scoring/threshold/safety-lexicon changes.** `git diff` confirms `services/
  meme_opportunity.py` and `services/meme_safety.py` are byte-identical to the prior checkpoint.
- **`meme_opportunity_mode` unchanged** — still `"off"` in `core/config.py`.
- **No secret exposure.** No `.env` value, API key, or credential was read, printed, or referenced
  anywhere in this phase's code, docs, or terminal output.

## 6. Tests

`tests/test_phase18_6_meme_calibration.py` — **58 tests**, all passing:

- Schema validation (7): blank defaults, `is_reviewed` transitions, `human_score` range
  enforcement (0-5), `extra="forbid"`, `algorithm_score` range enforcement, completed-annotation
  JSON round-trip.
- Selection logic (11): `select_diverse_by_category`/`select_random` — count limits, empty/small
  pools, no duplicates, determinism, and (for the diverse selector specifically) real coverage of
  every available category.
- Record building / group separation (9): correct `MemeReviewGroup` mapping per label, the
  deliberate `ValueError` for a `HIGH`-labeled record (no calibration group is defined for it —
  Groups A/B/C only, per the brief), algorithm-field pass-through, excerpt truncation, `None`
  content handling, blank human fields, and dataset group-count aggregation.
- Markdown rendering (4): every human field renders as the literal placeholder (never a real
  `ACCEPT`/`WEAK`/`REJECT` value), correct group headers/counts, the empty-group message, and
  sequential numbering across groups.
- Metric calculation (14): `opportunity_classifier_metrics` (precision strict/lenient, false
  positive rate, false negative rate + examples, unreviewed-record exclusion, the `recall=None`
  honesty gate), `score_correlation` (perfect correlation, <2-points, no-variance, and
  missing-human-score exclusion cases), `category_analysis` (averaging, sorting, unreviewed
  exclusion), `safety_analysis` (correct/false/questionable block counts and examples).
- Analysis-script honesty gate (3): `analyze()` returns `"pending"`/`"partial"`/`"complete"`
  correctly based on how much of the dataset has actually been reviewed.
- Committed-artifact regression guards (3): the real, committed
  `scripts/phase18_6_calibration_dataset.json` has the expected 20/20/10 group sizes and every
  `human_*` field genuinely `null`; the real, committed `docs/phase18_6_human_review_packet.md`
  has ≥50 blank decision fields and never a real decision value (reads the actual files, not just
  generator intent — mirrors Phase 18.5 M3's own established precedent).
- Import-boundary / no-mutation checks (5): the AST-based forbidden-import check (parametrized over
  3 files), the textual no-write-statement checks for both scripts, and the stronger
  no-database-import-at-all check for the analysis script.

**Targeted regression** (`pytest -k "phase18 or meme"`, 261 tests): 251 passed, 10 failed — all 10
failures are the exact same pre-existing `meme_candidates`-table-missing failures Phase 18.5 M4
already identified and attributed to a gap between Phase 18's accepted migration and real
production's actual schema state (unrelated to this phase; `services/meme_opportunity.py` and
`services/meme_safety.py` are untouched). Zero new failures.

**Full repository regression**: see Appendix.

## 7. Known limitations

- **Human review has not happened yet — by design.** Every `human_*` field in both
  `scripts/phase18_6_calibration_dataset.json` and `docs/phase18_6_human_review_packet.md` is
  genuinely blank. `scripts/phase18_6_calibration_analysis.py`, run against the dataset as it
  stands today, honestly reports `"status": "pending", "message": "Calibration dataset prepared,
  human review pending."` — no metric in this report is a real, human-verified number; none was
  invented.
- **True statistical recall is not computable from this sample**, even after review — it would
  require knowing the total count of real meme-worthy events across the full, mostly-unreviewed
  12,430-event population, which a targeted 50-item sample cannot supply.
  `opportunity_classifier_metrics()` returns `recall: None` with this reason stated explicitly,
  rather than approximating it.
- **Group A's category diversity is capped by the real data, not by this phase's selection logic**
  — only 4 of 8 `EventCategory` values have ever produced a `MEDIUM`-labeled record (a Phase 18.5
  M2 finding this phase inherits, not something Phase 18.6 introduces).
- **Precision/false-positive framing is one defensible choice among several** — `precision_strict`
  counts only `ACCEPT` as a true positive, `precision_lenient` counts `ACCEPT` or `WEAK`; both are
  reported side by side specifically because collapsing the human's 3-way `Decision` into a single
  binary would hide that ambiguity (documented explicitly in `opportunity_classifier_metrics()`'s
  own docstring, not left implicit).
- **The already-known production migration gap persists.** Real `ai_newsroom` is still one
  `alembic` revision behind head (Phase 18's `meme_candidates` table) — this phase did not touch
  it (applying a migration to real production is an explicit stop condition requiring separate
  confirmation) and it continues to cause the same 10 pre-existing test failures Phase 18.5 M4
  first surfaced.

## 8. Next recommendation

1. **Immediate next step (human, not engineering):** a human reviewer fills in
   `docs/phase18_6_human_review_packet.md`'s 50 items (or edits
   `scripts/phase18_6_calibration_dataset.json` directly — both represent the same underlying
   data), then runs `python scripts/phase18_6_calibration_analysis.py` to get real
   precision/recall/false-positive/correlation/category/safety metrics.
2. Once reviewed, compare those metrics against the two open questions Phase 18.5 M2 already
   raised — whether `_READY_THRESHOLD`/`_REVIEW_THRESHOLD` in `services/meme_opportunity.py` are
   miscalibrated-strict or correctly-conservative, and whether the confirmed literal-keyword safety
   false positives (Phase 18.5 M4 §6) warrant a lexicon fix.
3. Only after that human-reviewed evidence exists should any change to `services/
   meme_opportunity.py`'s thresholds/keywords, or to `meme_opportunity_mode`, be considered — and
   that remains a separate authorization decision, not implied by this report.

**Phase 19 is explicitly not started by this report.** Engineering work stops here pending separate
confirmation, per instruction.

---

## Appendix: full regression suite

`python -m pytest -q` (full suite, real `ai_newsroom`-backed database): **2,404 tests collected,
2,375 passed, 29 failed** (2,413.44s / 40m13s).

**Comparison against Phase 18.5's own baseline** (`docs/phase18_5_final_report.md` Appendix: 2,346
collected, 2,315 passed, 31 failed): the 29 failures here are an exact **subset** of that 31-item
failure set — every one of the 10 `meme_candidates`-table-missing failures
(`test_phase18_db_integration.py` ×7, `test_phase18_meme_pipeline_offline_e2e.py` ×3) and all 19
pre-existing FK-violation/data-state failures (`test_capability_executor.py` ×8,
`test_content_generation_integration.py` ×1, `test_content_worker_cycle.py` ×2,
`test_content_worker_cycle_image_preview.py` ×1, `test_editorial_inbox_service.py` ×1,
`test_editorial_scoring.py` ×2, `test_fact_safety.py` ×2, `test_news_handler.py` ×1,
`test_phase10_workflow_integration.py` ×1) recur unchanged. **Zero new failures.**

The only difference is the 2 fewer failures: `test_analysis_worker_main.py`/
`test_content_worker_main.py::test_cycle_level_infrastructure_failure_logs_and_waits_for_next_
interval` — the same test Phase 18's own final acceptance already documented as genuinely
timing-flaky — passed on this run instead of failing, consistent with non-determinism rather than
a fix (nothing in Phase 18.6 touches either file). `git diff --stat checkpoint/phase18-5-final-
complete..HEAD` confirms zero modification to any of these 12 failing test files or anything they
import beyond what Phase 18.6 itself newly added.

All **58 new Phase 18.6 tests pass** and are among the 2,375 passed — zero among the 29 failed.
`ruff check` on all 6 new non-test files: all checks passed. `mypy --ignore-missing-imports` on all
6 new non-test files plus the test file: no issues found.
