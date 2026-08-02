# Phase 17 — Final Engineering Completion Report

## 1. Executive summary

Phase 17 ("Editorial Intelligence") built a chain of deterministic, zero-new-LLM-call shadow
assessments over the existing AI Newsroom content-generation pipeline — from a first output-
quality discovery pass (M0) through an integrated, advisory validation layer (M6) and a cutover-
readiness package (M6.1). Every milestone is disclosed honestly, including two real, measured
shortfalls (M3's original under-length issue, fixed same-milestone; M4's empty-output truncation
bug, root-caused and fixed in M4.1) and one still-open tuning gap (M5's 0%-READY calibration,
inherited into M6, not yet fixed). **Nothing in Phase 17 is active in production.** All feature
modes remain at their safe defaults; production workers remain stopped; zero paid LLM calls were
made during this session beyond the M4.1 replay (7 calls, $0.026632, separately confirmed by the
user before execution).

## 2-9. M0-M4.1 results

Full detail in each milestone's own report — summarized, not re-litigated:

- **M0** (`docs/phase17_m0_output_quality_discovery_report.md`): discovery only. Found the
  headline-rewrite proxy measured 0% vs. a real 18.75-21.9% manual rate; baseline drafts are
  20-55 words, 100% single-paragraph; `NewsEvent.summary` is a dead field (0.017% populated).
- **M1** (EditorialBrief shadow): deterministic pre-Copywriting plan, shadow-only, zero LLM.
- **M2** (Channel/Topic Relevance shadow): deterministic classifier; correctly flags the Netflix/
  Walking Dead case REJECT (later confirmed again in M6, §8).
- **M3** (Adaptive Length shadow): real candidate comparison, 32 pinned cases, $0 initial +
  real paid comparison run; disclosed an under-length tendency, informed M4's own design.
- **M4** (Beginner-Friendly Copywriting): real 32-case paid comparison ($0.17785), 18/25 (72%)
  strictly preferred over M3; disclosed a real 7/32 (21.9%) empty-output truncation bug — final
  verdict **TUNING REQUIRED**, not masked.
- **M4.1** (reasoning-budget fix): root-caused the M4 bug (`reasoning_effort="medium"` starving
  the shared output-token budget), fixed to `"low"` (+ a controlled `"none"` retry), replayed
  exactly the 7 affected cases live ($0.026632, 7/7 valid, 0 still-empty). Merged 32-case result:
  0% truncation (was 21.9%), safe-range compliance 59.4% (was 46.9%), 96.9% preferred-or-tied vs.
  M3. **Total Phase 17 comparison-mode cost across M3+M4+M4.1: $0.204482.**

## 9 (cont). M5 results

`docs/phase17_m5_editorial_completeness_gate_shadow_report.md`. Deterministic Editorial
Completeness Gate (14 criteria) + Fact Safety calibration layer (4 named suppression rules) over
`CandidateFactSafetyAudit` (never rewritten). Real backtest: 269 baseline + 32 M3 + 32 M4/M4.1
candidates, 96 gold-labeled cases. Calibrated Fact Safety FAIL count cut 87.5%/75%/67% across the
three datasets; both M4.1-disclosed false positives confirmed fixed. **Honest disclosure: false
READY rate 0% (met) but false NOT_READY rate 100% on a 10-case subset (missed)** — verdict
**SHADOW READY, TUNING REQUIRED**.

## 10. M6 results

`docs/phase17_m6_integrated_editorial_validation_report.md`. Combines Relevance + Completeness +
Fact Safety + real Telegram delivery-feasibility (reusing `bot/formatting.py` unmodified) into one
`IntegratedEditorialValidation`. Netflix/Walking Dead confirmed `REJECT_RECOMMENDED` in all three
dataset variants. 100% text-message fit, 100% caption-fit among the cases with known image state,
0% technical blocker, 0% URL-in-body, 0% silent truncation across all 333 backtested cases. 0%
READY_FOR_EDITOR — entirely inherited from M5's own disclosed gap, no new M6 defect.

## 11. Cutover readiness

`docs/phase17_m6_1_production_cutover_readiness_report.md` + runbook. Preflight script
(`scripts/phase17_cutover_preflight.py`) passes cleanly against the real current state. Staged
rollout plan (Stage 0-5) documented; only Stage 1 (shadow-only, zero cost) is realistically
authorizable today. Stages 3-5 explicitly require engineering not yet built and/or a separate
calibration milestone.

## 12. Feature-mode inventory

| Flag | Default | Current | States |
|---|---|---|---|
| `llm_budget_mode` | shadow | shadow (unchanged) | off/shadow/enforce |
| `fact_safety_mode` | shadow | shadow (unchanged) | off/shadow/enforce |
| `image_intelligence_mode` | off | off (unchanged) | off/shadow |
| `image_candidate_persistence_mode` | off | off (unchanged) | off/metadata/finalists |
| `editorial_brief_mode` | off | off (unchanged) | off/shadow |
| `channel_relevance_mode` | off | off (unchanged) | off/shadow |
| `adaptive_length_mode` | off | off (unchanged) | off/shadow/comparison |
| `beginner_copywriting_mode` | off | off (unchanged) | off/shadow/comparison |
| `editorial_completeness_mode` | off | off (unchanged) | off/shadow (new, M5) |

No `.env` value was changed during this entire session.

## 13. Quality improvements

M3/M4/M4.1: 96.9% preferred-or-tied vs. M3, 62.5% strictly preferred, 0% misleading/filler/
repetition among 32 successful candidates, 0% truncation (post-M4.1). M5/M6: Fact Safety false-
positive rate cut roughly 70-87% across three real datasets; headline-rewrite detection replaced
(M0's 0%-effective proxy → a working, measured HIGH/MEDIUM/LOW signal).

## 14. Relevance improvements

M2's channel classifier, re-verified independently in M6: correctly isolates the one known
off-topic regression case (Netflix/Walking Dead) across all three dataset variants, zero other
false REJECTs found in the 96-case gold set.

## 15. Fact Safety results

Raw audit unmodified throughout. Calibration layer (M5) reduces measured false positives
substantially (§9 above) while preserving 100% true-positive retention and 0 false negatives on
9 explicit regression fixtures. One known, disclosed, out-of-scope false positive remains
(`eae93502`, a money-range parsing gap in the underlying Phase 15 M5 extractor).

## 16. Cost summary

| Milestone | Real paid calls | Cost |
|---|---|---|
| M3 | 32 | included below |
| M4 | 32 | $0.17785 |
| M4.1 | 7 | $0.026632 |
| M5 | 0 | $0 |
| M6 | 0 | $0 |
| M6.1 | 0 | $0 |
| **Total Phase 17** | **71** | **$0.204482** |

## 17. Regression summary

Real, actual pre-Phase-17-M5 full-suite baseline (confirmed by a real run at the start of this
session, not assumed): **19 failed / 1873 passed**. Targeted M5/M6/M6.1 suites: 76 + 22 + 9 = 107
tests, all passing. **Full-suite regression after all of M5+M6+M6.1 (confirmed, real run, 1389.5s):
19 failed / 1949 passed.** The 19 failures are the exact same 19 test names as the pre-M5
baseline, byte-for-byte (`test_capability_executor.py` ×8, `test_content_generation_integration.py`
×1, `test_content_worker_cycle.py` ×2, `test_content_worker_cycle_image_preview.py` ×1,
`test_editorial_inbox_service.py` ×1, `test_editorial_scoring.py` ×2, `test_fact_safety.py` ×2,
`test_news_handler.py` ×1, `test_phase10_workflow_integration.py` ×1) — **zero new regressions**
introduced by M5, M6, or M6.1.

## 18. Known limitations

- M5's own 0%-READY / 100%-false-NOT_READY-on-a-10-case-subset gap (disclosed in full in the M5
  report §23/§27) — the single most significant open editorial-calibration issue in Phase 17.
- `eae93502`'s Fact-Safety false positive (money-range parsing gap) remains unresolved, out of
  M5's declared calibration scope.
- `background_context_covered` is `NOT_APPLICABLE` for all 333 backtested cases — a pre-existing
  M1 limitation (the field is rarely/never populated by `build_editorial_brief()`).
- Stage 3+ canary delivery code does not exist yet — explicitly deferred, not started.
- Cross-language (English `EditorialBrief.headline_fact` from `NewsEvent.title` vs. Russian draft
  text) evidence matching has a real, narrow gap, partially mitigated during M5 (token-overlap
  fallback) but not fully solved — see M5 report §8/§23.

## 19. Human actions required

1. Review `docs/phase17_m6_human_acceptance_packet.md`.
2. Decide, in writing, whether to authorize Stage 1 (shadow-only, zero cost) per
   `docs/phase17_m6_1_production_cutover_runbook.md`.
3. If authorizing: follow the runbook's exact manual steps (this was never executed
   automatically).
4. Independently: consider whether M5's completeness-gate tuning gap warrants a dedicated
   follow-up milestone before Stage 1's `editorial_completeness_mode=shadow` is turned on, since
   even shadow-only persistence of a miscalibrated verdict could mislead a future human reader of
   `step_results` if not clearly understood as "conservative, not authoritative" (already
   disclosed in every relevant report, but worth re-stating here explicitly).

## 20. Cutover checklist

See `docs/phase17_m6_1_production_cutover_readiness_report.md`'s own "Acceptance checklist" -
everything is checked except the one item requiring the user: human authorization for Stage 1.

## 21. Rollback summary

Documented in the runbook: revert 5 env vars to `off`, restart 4 services, no migration exists to
roll back, no data needs restoring.

## 22. M7 boundary

M7 (Storyline Memory) was **not started** — it requires its own separate persistent-state design
(explicitly out of scope for this session per the user's own instruction) and is not referenced by
any M0-M6.1 code path.

## 23. Final engineering verdict

**PHASE 17 ENGINEERING COMPLETE — HUMAN CUTOVER REQUIRED.** M5 and M6 both close with an honestly-
disclosed tuning gap rather than a false "fully validated" claim, consistent with this project's
own established M0/M3/M4 precedent. No technical blocker exists to Stage 1 shadow authorization;
no component is ready for enforcement (Stage 5) without further calibration work. Nothing was
activated, nothing was pushed, no production data was touched, no secrets were committed.
