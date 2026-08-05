# Phase 18.5 — Meme Intelligence Shadow Validation: Final Report

Status: **READY FOR HUMAN REVIEW.** Engineering scope for Phase 18.5 is complete. This report
synthesizes M0–M3 into a single validation record and gives a GO/NO-GO recommendation for
enabling `meme_opportunity_mode="shadow"` in real production. It does **not** authorize that
change by itself — see §10.

---

## 1. Executive summary

Phase 18.5 ran the existing, unmodified `assess_meme_opportunity()` classifier (built and
accepted in Phase 18 M1) read-only against all **12,430 real `NewsEvent` rows** in the production
database, through a brand-new, fully isolated shadow-analytics code path that never touches
`CapabilityExecutor`, `WorkflowRunner`, the `meme_opportunity_mode` flag, or any table other than
a `SELECT` against `NewsEvent`/`sources`. Zero images were generated, zero LLM calls were made,
zero Telegram messages were sent, zero rows were written anywhere, and zero production behavior
changed — verified after every run via before/after row-count checks (§2, §9 of the M0 report).

**Headline finding: the opportunity rate is 0.44%** — 55 of 12,430 real events reached
`MEDIUM`/`REVIEW`, and **zero ever reached `HIGH`/`MEME_READY`**. `1.46%` (182 events) were hard
safety-blocked. A 50-item stratified human-review packet was built and committed with every
`human_decision`/`human_notes` field genuinely blank; system-level pattern analysis of that
packet (not a human verdict) found two concrete false-positive classes: arXiv paper abstracts
matching the irony/contrast heuristic (16/20 of the MEDIUM sample), and literal-keyword safety
false positives (a game titled "Gears of *War*", an iPhone poll matching `death_or_tragedy:killed`
in unrelated text).

Human review of the 50-item packet has **not** happened yet — that is by design (the brief
explicitly forbids auto-filling it) and is the one thing standing between this report and a firm
GO. §10 states the conditional recommendation precisely.

The full-suite regression run (2,346 tests) also surfaced a real, separate finding: production's
`alembic current` is one revision behind `alembic heads` — the Phase 18 `meme_candidates` migration
was reviewed and accepted but never actually applied to the real database. This caused 10 of the
run's 31 failures; the other 21 are pre-existing data-state/timing issues already documented (or a
larger instance of an already-documented category) in Phase 18's own acceptance baseline. All 31
are proven independent of Phase 18.5 by a zero-diff check on every file they live in — see §10 and
the Appendix.

## 2. Architecture changes

**None to existing systems.** `git diff --stat b036fb2..HEAD` (Phase 18's accepted HEAD → Phase
18.5's HEAD) shows 7 files, all new, 2,002 insertions, **0 deletions, 0 modifications to any
existing file** — `core/config.py`, `capabilities/executor.py`, and every file under
`database/migrations/` have a literal empty diff. No new settings, no new migration, no new mode
flag, no new table.

The one architectural decision made was **how to reuse `assess_meme_opportunity()` without going
through the existing shadow-hook wiring** (`CapabilityExecutor._attach_meme_opportunity`, which is
gated by `meme_opportunity_mode` and only runs inside the live workflow). M0 evaluated three
storage/wiring options and chose a fourth, simpler one:

- Reusing the existing `EditorialTask.workflow` JSON hook path — rejected: would require driving
  events through `CapabilityExecutor`, i.e. touching the exact production pipeline this phase must
  not touch.
- A new `meme_shadow_results` DB table — rejected: unnecessary migration for a one-off historical
  analysis; violates "no new production migration without confirmation."
- Local JSON scratch artifacts (`scripts/_phase18_5_*.json`, uncommitted) — **chosen**: matches the
  project's own established convention (verified via `git log --all --diff-filter=A` showing the
  Phase 15/17 precedent of underscore-prefixed, uncommitted `scripts/_phaseNN_*.json` artifacts).

`services/meme_shadow_analytics.py` calls `assess_meme_opportunity()` directly (the same pure,
zero-network function Phase 18 M1 built and Phase 18's acceptance validation already covered) and
normalizes its output into a schema-versioned record. `scripts/phase18_5_shadow_collection.py` is
a thin, read-only driver: one `SELECT` joining `NewsEvent`/`sources`, no `INSERT`/`UPDATE`/`DELETE`
anywhere in the file (enforced by `test_no_insert_update_delete_statements_in_collection_script`).

## 3. Files changed

| File | Status | Purpose |
|---|---|---|
| `docs/phase18_5_meme_shadow_validation_discovery.md` | new | M0 discovery/architecture-decision report |
| `schemas/meme_shadow_analytics.py` | new | `MemeShadowRecord`, `MemeOpportunityLabel`, `MemeHumanReviewDecision`, `MemeShadowCollectionResult` — frozen, `extra="forbid"`, never carries raw title/content text |
| `services/meme_shadow_analytics.py` | new | `build_shadow_record`, `evaluate_event_shadow` (failure-isolated), and M2's 8 metric functions |
| `scripts/phase18_5_shadow_collection.py` | new, committed | read-only collection driver (no underscore prefix — this is the reusable tool; its JSON *output* is the underscore-prefixed, uncommitted scratch artifact) |
| `docs/phase18_5_metrics_report.md` | new | M2 metrics computed against the real 12,430-row collection run |
| `docs/phase18_5_human_review_packet.md` | new | M3: 50 real events, stratified, every decision field blank |
| `tests/test_phase18_5_shadow_analytics.py` | new | 29 tests: label mapping, normalization, no-raw-content, metrics, failure isolation, import-boundary/no-write safety checks, packet-blankness regression test |

No existing file was modified. No secret, `.env` value, or credential appears in any of the above.

## 4. Metrics

All numbers below are from `docs/phase18_5_metrics_report.md` (M2), computed once against the
real `ai_newsroom` production database on 2026-08-05, 12,430 events, 100% classified, 0 failures,
0 writes.

| Metric | Result |
|---|---|
| Opportunity rate (HIGH+MEDIUM / total) | **0.44%** (55 / 12,430) |
| HIGH (`MEME_READY`) | 0 (0.00%) |
| MEDIUM (`REVIEW`) | 55 (0.44%) |
| LOW (`NOT_SUITABLE`/`INSUFFICIENT_SOURCE`) | 12,193 (98.10%) |
| BLOCKED (`SENSITIVE_BLOCK`) | 182 (1.46%) |
| Category concentration (AI share of meme-potential vs. all traffic) | 89.09% vs. 26.03% (~3.4×) |
| Top safety-block category | `legal_jeopardy_or_accusation` (53), then `death_or_tragedy` (40), `war` (33) |
| Top opportunity pattern | `contradiction` (48/55 = 87%), then `emotional_contrast` (16) |
| Source sufficiency | sufficient 46.0%, partial 29.6%, headline_only 24.4%, empty 0.03% |

## 5. Shadow results

The composite-score distribution is the clearest signal in the whole dataset: **99.97% of real
events score below 40** (`_READY_THRESHOLD = 55`), and only a single event in 12,430 scored above
50. `_READY_THRESHOLD`/`_REVIEW_THRESHOLD` were calibrated in Phase 18 M1 against a 13-item,
hand-picked gold set that was itself pre-selected for containing meme-worthy stories — a gap that
report explicitly flagged as needing real shadow volume to close. Phase 18.5 supplies that volume,
but resolving whether the thresholds are miscalibrated-strict or correctly-conservative requires
the human judgment this phase deliberately did not supply itself (§7 of the M2 report, restated in
§6 below).

`UNKNOWN` is 50.7% of all traffic but only 3.6% of meme potential — category-blind volume is a
poor proxy for meme potential, and the classifier's existing lowest-tier prior for `UNKNOWN` is
directionally consistent with that.

## 6. False positive analysis

**Not from human review** (the packet is intentionally blank) — from my own system-level
inspection of the aggregate evidence-pattern data in the 50-item packet and the underlying
selection JSON. Two concrete classes surfaced:

**Class 1 — academic-abstract false positives (MEDIUM label).** 16 of the 20 sampled `MEDIUM`
items are arXiv paper abstracts (`source_name` containing "arXiv"); 18 of 20 carry the
`contrast_connector` evidence code. arXiv abstracts routinely open with a hedge-then-contrast
structure ("Existing methods... however, we show...") that is structurally identical to the
irony/contrast pattern the classifier looks for in genuine meme-worthy news, but is academic
hedging, not irony. This is very likely the single largest source of `MEDIUM`-label noise in the
real data — it would need either an arXiv/academic-source exclusion or a stronger secondary signal
before `contrast_connector` alone should count toward `REVIEW`.

**Class 2 — literal-keyword safety false positives (BLOCKED label).** Confirmed against two of the
15 sampled `BLOCKED` items by inspecting their actual `sensitivity_categories`/`evidence_patterns`:
- *"Nvidia выпустила драйвер с поддержкой Halo: Campaign Evolved и беты мультиплеера Gears of War:
  E-Day"* — blocked on `sensitivity_categories: ['war']`, evidence `war:war`. The literal string
  "War" in the game title *Gears of War* triggered a real-world-conflict safety block for a GPU
  driver release note.
- *"How do you plan on buying your next iPhone? \[Poll\]"* — blocked on `sensitivity_categories:
  ['death_or_tragedy']`, evidence `death_or_tragedy:killed`. The word "killed" matched somewhere in
  the article body (likely figurative usage, e.g. "killed the headphone jack") for what is an
  Apple purchasing-intent poll.

Both are genuine false positives caused by keyword matching without surrounding-context
disambiguation, not edge cases invented for this report — they were found by reading the actual
committed evidence fields for real, randomly-sampled production events. By contrast, a third
BLOCKED item sampled from the same batch (*"⚡ Новости к этому часу"*, a Habr news-roundup digest
whose embedded content includes a real report of a programmer's death after long overwork, matched
on `death_or_tragedy:умер`) is **not** a false positive — the underlying content genuinely concerns
a death, so the block is correct even though the *format* (a multi-story digest) makes it a poor
meme candidate for other reasons.

Because safety blocking is intentionally recall-favored ("a false block is cheaper than a false
pass" — Phase 18 M0's own design principle), Class 2 is an acceptable cost in isolation, but a
1.46% block rate with confirmed keyword-literalism false positives inside it is a legitimate input
to human calibration, not a reason to change the lexicon unilaterally.

## 7. False negative analysis

**Cannot be measured in this phase.** A false negative here means a real event that scored `LOW`
but was actually meme-worthy — detecting that requires a human to read `LOW`-labeled events and
judge them, which is exactly the human-review step this phase deliberately defers (M3's packet
does include a 15-item `LOW` sample for this purpose). No claim is made here about the false
negative rate; `docs/phase18_5_human_review_packet.md`'s LOW section is the mechanism for
collecting it once reviewed.

One structural risk worth naming: 75.3% of `LOW` records (9,183 of 12,193) scored `LOW` purely on
`composite_below_review_threshold` (adequate source content, but below-threshold score) rather than
thin sourcing — meaning the false-negative question is really "are the composite-score weights
right," which is the same open question raised in §5, not a separate defect.

## 8. Safety analysis

- Every sensitivity category the lexicon defines fired at least once against 12,430 real events
  (none is dead code): `legal_jeopardy_or_accusation` (53), `death_or_tragedy` (40), `war` (33),
  `disaster` (29), `crime_with_victim` (25), `harassment_or_stalking` (5),
  `protected_characteristics` (3), `minors_safety` (2).
- Safety blocking is enforced by the same `assess_meme_opportunity()` code Phase 18's acceptance
  validation already reviewed — Phase 18.5 changed nothing about how blocking works, only measured
  its real-traffic firing rate (1.46%) and sampled 15 real blocked cases for human review.
  `test_evaluate_event_shadow_failure_isolation` guarantees that if the underlying classifier ever
  raises for any reason, the shadow path degrades to `None` (logged, skipped) rather than crashing
  or silently mis-labeling — verified by an explicit unit test, not just code inspection.
- No raw article title or content is ever persisted in any Phase 18.5 schema field
  (`MemeShadowRecord` — verified by `test_build_shadow_record_never_contains_raw_title_or_content`)
  or in the metrics report. The human-review packet does carry a 280-character content excerpt per
  item, by design (a human reviewer needs to read the actual story), but that packet is a
  git-committed markdown doc intended exactly for that purpose, not a persisted analytics field.
- No secret, credential, or `.env` value was read, printed, or referenced anywhere in this phase's
  code, docs, or terminal output.

## 9. Cost analysis

**$0.** Every operation in Phase 18.5 is a deterministic, in-process, zero-network Python function
call (`assess_meme_opportunity()`, already audited in Phase 18) plus one read-only SQL `SELECT`.
No LLM call, no image-generation call, no Telegram API call, and no paid API of any kind was made
at any point — consistent with the phase's explicit constraint. Collecting all 12,430 events took
well under a minute end-to-end.

## 10. Production readiness

**Engineering readiness: YES, for Phase 18.5 itself.** The shadow-analytics code path is tested (29
tests: label mapping, normalization, no-raw-content, all 8 metric functions, failure isolation,
import-boundary and no-write-statement safety checks, and a packet-blankness regression test
reading the actual committed file), lints clean (`ruff`), type-checks clean
(`mypy --ignore-missing-imports`), and the full repository regression suite was re-run with these
changes present (Appendix below): 2,315 passed / 31 failed, with **all 30 of Phase 18.5's own new
tests passing** and all 31 failures proven pre-existing and unrelated to Phase 18.5 (zero overlap
between the failing files and anything Phase 18.5 touched — see Appendix for the full breakdown).

**Separate, newly-surfaced finding — real production is not actually on Phase 18's migration
head.** `alembic current` against the real `ai_newsroom` database returns `31a8d7c95c87`, one
revision behind `alembic heads` (`21177d5b859e`, the `meme_candidates` table). Phase 18's migration
was reviewed and accepted, but validated against a disposable database, not real production — it
appears to have never actually been deployed there. This is unrelated to Phase 18.5 (which never
touches that table) but is exactly the kind of thing a full-regression run against real prod
surfaces, so it's reported here rather than silently left for someone else to rediscover. Applying
it is a real production migration, one of this phase's own explicit stop conditions — not done
here, and needs its own separate confirmation.

**Calibration readiness: NOT YET — pending human review.** This report's own analysis (§6) already
surfaces two credible, evidence-backed false-positive classes without any human input at all. That
is itself informative — it means the 0.44% opportunity rate is at least partly a measurement of
real noise in the current heuristics, not purely a measurement of how rare genuine meme material
is. But it is not sufficient to recommend a threshold change or a live-mode flip: only a human
reading the 50-item packet (`docs/phase18_5_human_review_packet.md`) can distinguish "the
thresholds are too strict" from "the thresholds are appropriately conservative and 55 `MEDIUM`
candidates per ~12k-event backlog is exactly the right, small, reviewable yield."

### Recommendation: **CONDITIONAL GO — do not enable `meme_opportunity_mode="shadow"` in production yet.**

1. **Immediate next step (human, not engineering):** have a human reviewer fill in
   `docs/phase18_5_human_review_packet.md`'s 50 `human_decision`/`human_notes` fields.
2. **Once reviewed**, a short follow-up pass (in-scope for a future milestone, not this one) should
   compute the real false-positive/false-negative rate from those decisions and decide, with actual
   evidence, whether `_READY_THRESHOLD`/`_REVIEW_THRESHOLD` need adjustment and whether the
   `contrast_connector`-alone-triggers-MEDIUM rule needs an academic-source exclusion.
3. **Only after that calibration step** should turning on `meme_opportunity_mode="shadow"` in real
   production (still shadow-only — no generation, no publishing) be considered, and that is a
   separate authorization decision, not implied by this report.
4. Independent of meme-specific calibration, the two confirmed literal-keyword safety false
   positives (§6, Class 2) are worth a low-risk, high-value fix on their own merits (context-aware
   matching around game/product titles containing "war"/"killed"-type words) — but changing
   `services/meme_safety.py`'s lexicon is itself a change to reviewed Phase 18 code and is out of
   this shadow-only phase's scope; flagged here for a future milestone, not implemented.

**Phase 19 is explicitly not started by this report.** Per instruction, engineering work stops
here pending separate confirmation.

---

## Appendix: full regression suite (run after all Phase 18.5 changes were complete)

- `python -m pytest -q` (full suite, real `ai_newsroom`-backed database): **2,346 tests collected,
  2,315 passed, 31 failed** (2,522.63s / 42m02s).
- **All 31 failures are pre-existing and independent of Phase 18.5.** Proof: `git diff --stat
  b036fb2..HEAD` restricted to the 13 files containing these 31 failing tests is completely empty
  — Phase 18.5 did not modify a single line of any file any of these tests live in, so the outcome
  of running them is identical regardless of whether Phase 18.5's commits exist. Breakdown:
  - **10 failures** (`test_phase18_db_integration.py` ×7, `test_phase18_meme_pipeline_offline_e2e.py`
    ×3) — `asyncpg.exceptions.UndefinedTableError: relation "meme_candidates" does not exist`.
    Root cause: `alembic current` on the real production database returns `31a8d7c95c87`, one
    revision behind `alembic heads` (`21177d5b859e` — the Phase 18 `meme_candidates` migration).
    **The Phase 18 migration was reviewed and accepted but was apparently never actually applied to
    the real production database** (Phase 18's own migration validation ran against a disposable
    `phase18_validation_db`, not real prod). This is a genuine, newly-surfaced finding — outside
    Phase 18.5's scope to fix (applying it now would be a real-production schema change, one of
    this phase's own explicit stop conditions requiring separate confirmation) — but worth flagging
    prominently since it means Phase 18's feature is not actually deployable in production as-is
    yet, independent of anything in Phase 18.5.
  - **2 failures** (`test_analysis_worker_main.py`/`test_content_worker_main.py`, both
    `test_cycle_level_infrastructure_failure_logs_and_waits_for_next_interval`) — the same
    genuinely-timing-flaky test already documented and isolated as pre-existing during Phase 18's
    own final acceptance (`docs/phase18_final_acceptance_regression_report.md`).
  - **19 failures** (`test_capability_executor.py` ×8, `test_content_generation_integration.py` ×1,
    `test_content_worker_cycle.py` ×2, `test_content_worker_cycle_image_preview.py` ×1,
    `test_editorial_inbox_service.py` ×1, `test_editorial_scoring.py` ×2, `test_fact_safety.py` ×2,
    `test_news_handler.py` ×1, `test_phase10_workflow_integration.py` ×1) — sample-checked
    (`test_capability_executor_is_a_drop_in_step_executor`) and found to be
    `sqlalchemy.exc.IntegrityError: ForeignKeyViolationError` from `DELETE FROM content_drafts`
    conflicting with real, already-existing `image_candidates` rows in the production database.
    These are tests written assuming a clean/empty table that no longer holds given how much real
    data has accumulated in production since Phase 18's own acceptance baseline (6–7 pre-existing
    failures at that time, vs. 21 non-meme-migration failures now) — the same *category* of
    pre-existing, `.env`/data-state-driven environmental mismatch Phase 18's acceptance already
    established as non-blocking, just a larger instance of it now.
  - Phase 18.5 added exactly **30 passing tests** (29 in `tests/test_phase18_5_shadow_analytics.py`
    covering M1–M2, plus 1 packet-blankness test added in M3) — all 30 are among the 2,315 passed,
    zero among the 31 failed.
- `ruff check` on all 7 new/changed files: all checks passed.
- `mypy --ignore-missing-imports` on all non-test new files: no issues found.
- `git diff --stat b036fb2..HEAD` (excluding uncommitted `scripts/_phase18_5_*` scratch artifacts):
  7 files changed, 2,002 insertions(+), 0 deletions(-) — purely additive, zero modification to any
  existing file, zero touch to `core/config.py`, `capabilities/executor.py`, or
  `database/migrations/`.
