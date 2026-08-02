# Phase 17 M6 — Integrated Editorial Validation

Status: **ENGINEERING VALIDATION COMPLETE — CONSERVATIVE BY DESIGN, NO PRODUCTION ACTIVATION.**
All numbers below come from a real, deterministic backtest
(`scripts/phase17_m6_integrated_validation_backtest.py`) over the same 269 baseline + 32 M3 + 32
M4/M4.1 candidates M5 already backtested — zero new LLM calls, zero Telegram sends, zero
`ContentDraft`/task-state mutation.

## 1. Objective

Validate the entire Phase 17 editorial pipeline (`EditorialBrief`, Channel/Topic Relevance,
`AdaptiveLengthPlan`, `BeginnerFriendlyPlan`, `CandidateFactSafetyAudit`,
`CalibratedFactSafetyAssessment`, `EditorialCompletenessAssessment`) as one integrated system,
without activating any of it in production — answering whether the integrated candidate is
consistently better than baseline, whether off-topic stories are caught, whether insufficient
sources are handled honestly, whether delivery is feasible, and what remains before cutover.

## 2. Starting state

Continued directly from `checkpoint/phase17-m5` (HEAD `efca310`), all M5 acceptance gaps already
disclosed (docs/phase17_m5_editorial_completeness_gate_shadow_report.md). Docker state
re-confirmed unchanged (`postgres`/`redis`/`backend` Up; workers/`telegram_bot` Exited).

## 3. Integrated pipeline

`services/integrated_editorial_validation.py::build_integrated_editorial_validation()` combines,
without re-deriving any of them: `ChannelFitAssessment` (M2, rebuilt fresh read-only via
`assess_channel_relevance()`), `EditorialCompletenessAssessment` + `CalibratedFactSafetyAssessment`
(M5, reused directly from the real M5 backtest output), and a new deterministic
`DeliveryValidation` (§11) reusing `bot/formatting.py`'s own unmodified renderer. Image context
(§12) is read from the real, already-persisted `image_candidates` table where joinable, `None`
("unknown") otherwise — never invented.

## 4. Schemas

`schemas/integrated_editorial_validation.py` (`INTEGRATED_EDITORIAL_VALIDATION_SCHEMA_VERSION =
"v1"`): `IntegratedEditorialValidation` (schema/validation_version, event_id, candidate_kind,
channel_fit_decision, source_sufficiency, completeness, fact_safety, delivery, image_context,
overall_decision ∈ {READY_FOR_EDITOR, REVIEW_REQUIRED, REJECT_RECOMMENDED, INSUFFICIENT_SOURCE,
TECHNICAL_BLOCKER}, blocking_reasons, review_reasons, warnings, confidence), plus
`DeliveryValidation` and `ImageContext` sub-schemas. No mutable defaults
(`Field(default_factory=list)` throughout).

## 5. Decision policy

Priority order (`build_integrated_editorial_validation()`): (1) empty/missing draft text →
`TECHNICAL_BLOCKER`; (2) missing required upstream assessment → `TECHNICAL_BLOCKER`; (3) does not
fit a text message even after truncation → `TECHNICAL_BLOCKER`; (4) completeness
`INSUFFICIENT_SOURCE` → propagated as-is; (5) channel fit `REJECT` → `REJECT_RECOMMENDED`; (6) any
of {calibrated Fact Safety `FAIL`, completeness `NOT_READY`, URL exposed in body, silent
truncation} → `REVIEW_REQUIRED` with the specific blocking reason; (7) else, `READY_FOR_EDITOR`
only if there are zero review-tier signals **and** completeness itself is `READY`; otherwise
`REVIEW_REQUIRED` with the specific review reason(s). Never enforced — advisory metadata only.

## 6. Dataset

Same three real datasets M5 already backtested, reused directly (no candidate regenerated): 269
production baseline drafts, 32 M3 candidates, 32 merged M4/M4.1 candidates (`scripts/
_phase17_m6_backtest_results.json`).

## 7. Gold-set mapping

M5's own 96-case gold set (`scripts/_phase17_m5_manual_gold_set.json`) is reused for continuity;
M6 does not re-derive new gold labels — `overall_decision` inherits every gap already disclosed in
M5's own `editorial_recommendation` accuracy (§22 of the M5 report). No new human labeling was
performed for M6 specifically (per this milestone's own "do not claim new human review unless
actually done by a human" instruction) — the human acceptance packet (§17) exists precisely so a
human can add that judgment before any cutover decision.

## 8. Relevance results

Channel/Topic Relevance rebuilt fresh for all 333 cases. The Netflix/Walking Dead regression case
(`fa60525c`) is **REJECT** in all three variants (baseline/M3/M4) — confirmed, required regression
behavior (§13). Across the full backtest: 1/269 baseline, 1/32 M3, 1/32 M4 cases are channel-fit
`REJECT` (the same underlying event in all three, since it's the same 32-case gold set embedded in
the 269) — no other high-confidence off-topic case was found in this sample.

## 9. Completeness results

Directly inherited from M5 (docs/phase17_m5_editorial_completeness_gate_shadow_report.md §19-21) —
0/333 `READY`, driven by the same disclosed evidence-matching/Fact-Safety-REVIEW-tier gap. M6 does
not re-tune M5's own completeness logic.

## 10. Fact Safety results

Directly inherited from M5's calibrated output (§14/§24 of the M5 report) — FAIL count reduced
87.5%/75%/67% across baseline/M3/M4 versus the raw audit.

## 11. Delivery results

`services/integrated_editorial_validation.py::validate_delivery()`, reusing `bot/formatting.py`'s
real `render_editorial_card()`/`EditorialInboxCard` unmodified. **Fits-text-message: 333/333
(100%)** — zero `TECHNICAL_BLOCKER` from delivery infeasibility. **Zero URL-exposed-in-body cases,
zero silent-truncation cases** across all 333. Caption-fit is only evaluable where image state is
known (§12): 67/269 baseline, 4/32 M3, 4/32 M4 — **100% caption-fit rate among the known subset**
in every dataset (no formatting defect found; no Telegram send path change was needed).

## 12. Image-context results

`has_image_candidate` read from the real, persisted `image_candidates` table (726 total rows in
the database) joined by `news_event_id`, `eligible_for_editorial` as the accept signal. Known for
67/269 (24.9%) baseline cases and 4/32 (12.5%) of the M3/M4 gold-set cases — the rest are honestly
`unknown` (`image_intelligence_mode` defaults to `"off"` in production for most historical tasks),
never guessed.

## 13. Regression cases

Netflix/Walking Dead (`fa60525c`): **REJECT_RECOMMENDED**, confirmed (§8). Clear AI/gadget/
regulation/business-tech articles: represented across the 96-case gold set, mostly
`REVIEW_REQUIRED` (§9's inherited gap). Headline-only ambiguous stories (`d9c0b32c`, `073437a9`,
`b0d0f1f3`): all route to `INSUFFICIENT_SOURCE`, none to a false `REJECT`/`TECHNICAL_BLOCKER`. The
arXiv/MLIP jargon case and the M3 unsupported-addition case are both present in the same 32-case
gold set carried through from M0-M4.1. All 7 M4.1-replayed cases are present in the M4 dataset
(§21 of the M5 report already covers their individual outcomes). See
`docs/phase17_m6_human_acceptance_packet.md` for 12 representative rows with full detail.

## 14. Failure analysis

Root cause of the near-total absence of `READY_FOR_EDITOR` (0/333): entirely inherited from M5's
own disclosed gap (docs/phase17_m5_editorial_completeness_gate_shadow_report.md §23/§27) — a
completeness-evidence-matching limitation plus a Fact Safety REVIEW-tier that is reached often by
design (uncertain-entity mentions deliberately never upgraded to "safe", Phase 15 M5's own rule).
M6 adds no new failure mode of its own: 0 `TECHNICAL_BLOCKER` across all 333 cases, 0 delivery
defects found.

## 15. Cost analysis

**$0.** No new LLM calls anywhere in M6 (`services/integrated_editorial_validation.py` never
imports the LLM Gateway — `tests/test_integrated_editorial_validation.py::test_no_llm_or_telegram_
import` verifies this statically). Total Phase 17 comparison-mode cost remains M4.1's own
already-reported $0.204482 (M3 §17 + M4 §17 + M4.1 §11 of their respective reports) — unchanged by
M5 or M6, both zero-LLM-call milestones.

## 16. Tests

22 targeted M6 tests (`tests/test_integrated_editorial_validation.py`): schema validation, 7
delivery-validation cases (short/long body, unknown image state, URL exposure, HTML-special-
character safety, hashtag-reserve accounting), 13 decision-logic branches (technical blocker,
insufficient source, channel reject → the Netflix/Walking Dead regression explicitly, serious
Fact Safety flag, completeness not-ready, URL exposure, silent truncation, all-clean READY, review
propagation, missing channel-fit-as-warning), 1 static no-LLM/no-Telegram-import check. All 22
pass. Ruff/Mypy clean on both new files. Full regression: see
`docs/phase17_final_engineering_completion_report.md` for the consolidated, single full-suite run
covering M5+M6+M6.1 together (avoiding three redundant ~25-minute full runs).

## 17. Human acceptance packet

`docs/phase17_m6_human_acceptance_packet.md` — 12 representative cases (REJECT_RECOMMENDED ×1,
REVIEW_REQUIRED ×8, INSUFFICIENT_SOURCE ×3), each cross-referenced to M3's/M4's own already-
completed real manual quality verdicts — never a new fabricated human opinion.

## 18. Cutover readiness

Engineering validation is complete; this milestone finds **no technical blocker** to cutover
readiness work proceeding (M6.1), but the completeness-gate's own disclosed tuning gap (0% READY
rate) means **no automated component should gate delivery on its own `overall_decision`** at this
time — human review remains required for every candidate regardless of the automated verdict,
consistent with M6.1's own planned Stage 1-2 (shadow/assessment only, no enforcement).

## 19. Remaining blockers

None technical. One editorial-calibration blocker carried over from M5: the 0%-READY / high-
false-NOT_READY gap (M5 report §23/§27) should get a follow-up tuning pass (better evidence
matching for `headline_fact_covered`/`event_details_covered`) before any automated component is
trusted for anything beyond advisory shadow output.

## 20. Definition of Done

- [x] Integrated schema created, versioned, no mutable defaults.
- [x] Combines Relevance + Completeness + Fact Safety + Delivery + Image context.
- [x] Netflix/Walking Dead → REJECT_RECOMMENDED confirmed on real data.
- [x] Delivery validation reuses the real, unmodified Telegram renderer — no send path changed.
- [x] 0% technical blocker rate, 0% empty output, 0% truncation, 0% URL-in-body, 0% silent truncation.
- [x] Zero new LLM calls, zero cost, zero Telegram sends, zero ContentDraft/task mutation.
- [x] 22 targeted tests passing; Ruff/Mypy clean.
- [x] Human acceptance packet created (12 cases, cites only pre-existing real manual verdicts).
- [x] Report created.
- [ ] 0% false READY / READY_FOR_EDITOR rate — trivially true (no READY_FOR_EDITOR verdict was
      ever issued), inheriting M5's own disclosed, unmet false-NOT_READY target as the reason.
