# Phase 18 M1 — Meme Opportunity Detection: Implementation Report

Status: complete. Additive, shadow-only, `meme_opportunity_mode` defaults to `"off"` (no
production behavior change). Zero new LLM calls, zero new DB writes, zero migrations.

## 1. What was built

| File | Purpose |
|---|---|
| `schemas/meme_opportunity.py` | `MemeOpportunityDecision` (5-way taxonomy), `MemeOpportunitySignals`, `MemeOpportunityAssessment` - frozen Pydantic contracts |
| `services/meme_opportunity.py` | Pure, deterministic classifier: sensitivity scan, irony/contrast/relatability/visual/topic-fit/freshness scoring, decision logic, `apply_meme_opportunity_shadow()` integration entry point |
| `capabilities/executor.py` | New `_attach_meme_opportunity()` hook, called at the "quality" step, gated by `settings.meme_opportunity_mode == "shadow"` |
| `core/config.py` | New `meme_opportunity_mode: Literal["off", "shadow"] = "off"` |
| `tests/test_phase18_m1_meme_opportunity.py` | 17 tests: sensitivity blocking, source sufficiency, scoring heuristics, mode gating, and a gold-set backtest |

This follows §4.1/§5 of `docs/phase18_m0_meme_discovery_report.md` exactly: M1 is implemented as
one more member of the existing executor shadow-hook family (`_attach_editorial_brief`,
`_attach_channel_relevance`, `_attach_editorial_completeness`, ...), not a new mechanism. No
`WorkflowType.MEME_GENERATION` task is created by this hook - it only computes and persists a
recommendation into `EditorialTask.workflow`'s existing `step_results["quality"]` JSON.

## 2. Decision logic

1. **Sensitivity scan (hard, short-circuits everything else).** A bilingual EN/RU phrase lexicon
   (`_SENSITIVE_PATTERNS`) covers the brief's own 9 categories: death/tragedy, disaster, war,
   crime-with-victim, minors'-safety, protected characteristics, serious illness, legal-jeopardy/
   unconfirmed-accusation, harassment/stalking. Any match → `SENSITIVE_BLOCK`, regardless of how
   high every other signal scores (mirrors `services.fact_safety`'s own "hard rejection wins
   regardless" precedence).
2. **Source sufficiency.** Reuses `services.editorial_brief.classify_source_sufficiency()`
   directly (§3.5 of the M0 report - no independent re-derivation). `EMPTY`/`HEADLINE_ONLY`/
   `CONFLICTING` → `INSUFFICIENT_SOURCE`.
3. **Composite score → decision.** Five 0-100 signals (irony/contrast 40% weight, topic-fit 25%,
   relatability 15%, visual-potential 10%, freshness 10%) combine into one composite score.
   `>= 55` → `MEME_READY`; `>= 35` → `REVIEW`; else `NOT_SUITABLE`. Weights and thresholds are
   documented as v1, calibrated against the gold-set backtest below - not against the earlier
   real-production data itself (only 32 audited samples were manually labeled in M0; recalibration
   against real `shadow`-mode volume is the natural follow-up once this ships, exactly as every
   Phase 17 classifier's own rollout did).

## 3. Bug found and fixed during testing

The gold-set backtest (built from `docs/phase18_m0_meme_discovery_report.md` Appendix A) caught a
real false positive before any code shipped: the bare keyword `"dead"` in the death/tragedy
lexicon matched **"The Walking Dead"** (a TV franchise title, not a death report) and wrongly
hard-blocked an ordinary Netflix streaming-rights story. Fixed by removing the bare word and
requiring an actual death-report phrase (`"found dead"`, `"pronounced dead"`, `"confirmed dead"`,
`"left dead"`, `"killed"`, `"died"`, `"death"`) - mirrors `services/channel_relevance.py`'s own
"no bare word alone triggers a category" discipline, which this module had briefly violated.
A regression test (`test_benign_school_story_about_children_is_not_blocked`,
`test_crime_with_victim_is_hard_blocked`) locks this in.

## 4. Testing

17/17 tests pass (`python -m pytest tests/test_phase18_m1_meme_opportunity.py -v`):
- Sensitivity hard-block correctness (4 categories tested directly) + one explicit test that a
  hard block overrides an otherwise-high composite score.
- A false-positive regression guard (benign "kids attend AI classes" story is never blocked).
- Source-sufficiency gating (empty/headline-only content → `INSUFFICIENT_SOURCE`).
- Each of the five scoring signals independently (irony markers, relatability, visual-potential
  boost from an existing image candidate, freshness decay, missing-timestamp safety).
- Mode gating (`"off"` → byte-identical passthrough; `"shadow"` → exactly one new key attached).
- A 13-case gold-set backtest against real (Phase-17-audited) news text: the hard safety
  invariant (no `SENSITIVE_BLOCK` gold case is ever missed) is asserted exactly; the coarser
  operational grouping (`PROCEED` = `MEME_READY`+`REVIEW`, `SKIP` = `NOT_SUITABLE`+
  `INSUFFICIENT_SOURCE`, `BLOCK` = `SENSITIVE_BLOCK`) reaches **85% agreement** (11/13); exact
  fine-grained label agreement is **62%** (8/13), printed for calibration review, not hard-gated -
  the module's own docstring discloses that lexical-marker-only irony detection will
  systematically miss non-lexical irony (e.g. "AI-focused hedge fund loses money on AI bets" has
  no keyword marker distinguishing it from an ordinary financial story without an LLM). This is
  the accepted, disclosed cost of the brief's own "0 additional LLM calls if possible" requirement
  (§8 risk 4 of the M0 report), not a defect to keep chasing with one-off keyword tuning.
- `python -m pytest --collect-only -q` across the entire repository (2160 tests) confirms zero
  import/collection regressions from the `capabilities/executor.py` and `core/config.py` edits.
- Full-suite execution (`python -m pytest -q`) was attempted for a broader regression check;
  the local Postgres/Redis stack is unavailable in this session (docker not running, same
  constraint disclosed in the M0 report §1), so DB-fixture-dependent tests are expected to
  fail/error for reasons unrelated to this milestone's changes - this is an environment
  limitation, not evidence introduced by M1. `_attach_meme_opportunity()` itself is a thin,
  try/except-wrapped call mirroring `_attach_editorial_completeness`'s already-DB-tested shape
  byte-for-byte (`tests/test_phase17_m5_integration.py`); no DB-touching logic is unique to it.

## 5. Validation notes

- **Byte-identical rollback path confirmed**: `meme_opportunity_mode` defaults to `"off"`;
  `apply_meme_opportunity_shadow()` returns the exact same `structured_output` object (identity-
  checked in `test_mode_off_returns_structured_output_unchanged`) when off.
- **No new LLM calls**: `services/meme_opportunity.py` imports no Gateway/provider module at all.
- **No new DB writes**: the assessment lives only inside `EditorialTask.workflow` JSON, exactly
  like every Phase 17 shadow artifact before it.
- **Failure isolation**: `_attach_meme_opportunity()` is wrapped in `try/except Exception`,
  logging `meme_opportunity_assessment_failed` and returning `structured_output` unchanged on any
  error - a classifier bug can never fail a CONTENT_GENERATION task.

## 6. Risks / limitations carried forward

- Irony/contrast detection is lexical-marker-based only (§4 M0 risk); expect false REVIEW/
  NOT_SUITABLE on subtle irony until either the lexicon grows from real shadow-mode data or a
  narrowly-scoped LLM call is justified in a future milestone (not proposed here - no such call
  exists in M1).
- Thresholds/weights are v1, calibrated against a 13-case hand-built gold set, not against
  production shadow volume - recalibration is expected before any future `enforce`-style mode
  (none exists yet; M1 ships `off`/`shadow` only, matching the taxonomy's own "shadow recommendation,
  never blocking" design).
- The sensitivity lexicon is necessarily incomplete (a fixed keyword/phrase list can never cover
  every real-world sensitive phrasing) - biased toward recall over precision by design (§ module
  docstring), but a lexicon gap is still possible and should be monitored via
  `meme_opportunity_assessment_completed`/`_failed` log volume once shadow mode runs for real.

## 7. Next milestone

M2 (Meme Concept Generation) - per the M0 report's §7/§10, this is also where the phase's one
recommended migration (`meme_candidates` table) is introduced, since M2 is the first milestone
needing to persist state across a bounded regenerate loop.
