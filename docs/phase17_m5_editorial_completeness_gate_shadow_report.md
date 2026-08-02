# Phase 17 M5 — Editorial Completeness Gate Shadow + Fact Safety Calibration

Status: **SHADOW READY — TUNING REQUIRED.** Every number in this report comes from a real,
deterministic backtest run (`scripts/phase17_m5_completeness_gate_backtest.py`) against already-
saved M0/M3/M4/M4.1 data — zero new LLM calls, zero cost. The gate itself is genuinely useful
(Fact Safety false-positive rate cut roughly in half to fully suppressed on real cases, headline-
rewrite detection fixed from M0's own 0% to a working signal) but the `editorial_recommendation`
verdict is measurably miscalibrated on one axis (a 100% false `NOT_READY` rate on a small, 10-case
subset of the 96-case gold set) — disclosed honestly below, not masked, matching this project's
own established M0/M4 precedent of reporting a real defect rather than a rounded-up success.

## 1. Objective

Build a deterministic, versioned Editorial Completeness Gate that shadow-assesses a finished
draft (production baseline or a saved M3/M4/M4.1 candidate) against its own upstream
`EditorialBrief`/`AdaptiveLengthPlan`/`BeginnerFriendlyPlan`/evidence/source sufficiency, plus a
calibration layer over the existing `CandidateFactSafetyAudit` that suppresses known false-
positive classes disclosed by M4.1 — as two clearly separate dimensions, never merged into one
opaque score. Zero new LLM calls, shadow-only, `ContentDraft`/task state/Telegram untouched.

## 2. Starting state

Restored and confirmed before any M5 work began: branch `feature/phase17-editorial-intelligence`,
HEAD `372b83f82ba9a215c3cf0f985c128817c5d13e26` (= `checkpoint/phase17-m4-1`), clean tracked
status (only known M0-M4.1 scratch JSON artifacts untracked), Docker state confirmed
(`postgres`/`redis`/`backend` Up; `automation_worker`/`news_analysis_worker`/`content_worker`/
`telegram_bot` all Exited), actual pre-M5 full-suite baseline confirmed by a real run: **19 failed
/ 1873 passed** (not the M4.1 report's own documented "20 failed / 1836 passed" — the suite grew
by M4.1's own 36 tests and one pre-existing failure resolved itself; used as this milestone's own
real regression baseline, not assumed).

## 3. M0–M4.1 evidence carried into M5

- M0 (`docs/phase17_m0_output_quality_discovery_report.md` §6): the old headline-rewrite proxy
  (vocabulary-overlap-only) measured **0.0% (0/269)** against a real manual-audit rate of
  **18.75-21.9%** — the exact gap M5's own `assess_headline_rewrite_risk()` targets.
- M4.1 (`docs/phase17_m4_1_reasoning_budget_fix_report.md` §11): 2 of 7 replayed candidates had a
  `CandidateFactSafetyAudit` `FAIL` later confirmed, by manual read, to be false positives —
  Russian declension mismatch (`fa60525c`, "Ходячих мертвецов" vs. "Ходячие мертвецы") and a
  definition/causal-hedge misclassification (`7352db1a`, "Corporation" + a hedge sentence). Both
  are this milestone's own primary, named calibration targets.
- M4 (`docs/phase17_m4_beginner_friendly_copywriting_report.md` §26): one already-disclosed false
  positive (`eae93502`, Moonshot AI) driven by a money-*range* parsing gap ("$1-2 млрд" partially
  matched as "2 млрд") — **out of M5's declared calibration scope** (not one of the named false-
  positive classes) and confirmed still present after calibration (§25 below).

## 4. Existing Quality behavior (discovery)

`capabilities/quality_capability.py` (`CAPABILITY_NAME = "quality"`) is a real, active production
Capability — a single LLM Gateway call per task, `prompts/quality/v3.yaml`, output
`{"passed": bool, "issues": list[str]}`, an LLM *judge*, not a deterministic check. It runs after
"copywriting" in every `CONTENT_GENERATION` workflow. `services/fact_safety.py`'s own
`apply_fact_safety()` already attaches a deterministic, zero-LLM baseline Fact Safety result at
this same step (Phase 15 M5), gated by `fact_safety_mode` (default `"shadow"`). No existing
completeness/duplication/style check exists anywhere in the pipeline; `QualityCapability`'s own
prompt only checks contradiction/omission/vagueness via LLM judgment, never deterministically.

## 5. Architecture decision (recorded before implementation)

M5 is a **standalone deterministic module pair**
(`services/editorial_completeness.py` + `services/fact_safety_calibration.py` +
`services/text_normalization.py`), never merged into `QualityCapability` (a different
responsibility — an LLM judge vs. a deterministic gate) and never modifying
`services/candidate_fact_safety.py`'s own raw audit. Integration point: a new attach hook at
`step.capability == "quality"` in `capabilities/executor.py`, running immediately after
`apply_fact_safety()`'s own baseline check (same step) — by this point every upstream shadow
artifact M5 needs already exists in `step_results` (`editorial_brief` from "intelligence",
`adaptive_length_plan`/`beginner_friendly_plan` from "copywriting"), and the real Copywriting
`title`/`body` is available. Result persisted as two new, purely additive keys on the "quality"
step's own result: `"editorial_completeness"` and `"calibrated_fact_safety"`. Gated by a new,
two-state-only `editorial_completeness_mode: Literal["off", "shadow"] = "off"` (no "comparison"
state — M5 never generates a candidate, so there is nothing for a paid mode to gate).

Anti-leakage discipline: every criterion is graded against `EditorialBrief`/evidence text, never
against the very plan's own recommended word range as "proof" the draft is good — range
compliance is its own separate, narrow criterion (`safe_length_compliance`), never conflated with
substantive completeness.

## 6. Completeness schemas

`schemas/editorial_completeness.py` (`EDITORIAL_COMPLETENESS_SCHEMA_VERSION = "v1"`,
`EDITORIAL_COMPLETENESS_POLICY_VERSION = "v1"`): `CompletenessCriterionResult` (criterion, status
∈ {pass, partial, fail, not_applicable, unknown}, score, required, evidence_available,
matched_evidence, missing_items, reason_codes, confidence) and `EditorialCompletenessAssessment`
(schema/policy_version, draft_kind, source_sufficiency, criteria, required/passed/partial/failed
counts, completeness_score, confidence, headline_rewrite_risk, safe_length_status,
paragraph_status, editorial_recommendation ∈ {READY, REVIEW, NOT_READY, INSUFFICIENT_SOURCE},
reason_codes). `schemas/calibrated_fact_safety.py` (`CALIBRATED_FACT_SAFETY_SCHEMA_VERSION = "v1"`):
`CalibratedFactSafetyAssessment` (raw_audit_status, calibrated_status, true_positive_flags,
suppressed_false_positive_flags — a `SuppressedFlag{flag, reason_code}` list, never a bare string
— unresolved_flags, severity, reason_codes, human_review_required). Every list field uses
`Field(default_factory=list)` — no mutable default is ever shared (`tests/test_editorial_
completeness.py::test_no_mutable_defaults`).

## 7. Required vs optional criteria

Implemented exactly per this milestone's own rules (`services/editorial_completeness.py`):
`headline_fact_covered` required iff `EditorialBrief.headline_fact` is set; `event_details_covered`
required iff `event_details` non-empty; `subject_explanation_covered` required only when
`BeginnerFriendlyPlan.explanation_required` AND subjects/terms are non-empty; `background_context_
covered`/`difference_or_change_covered` required only when their own evidence is non-empty;
`why_it_matters_covered` required iff evidence present (further gated by
`why_it_matters_required` when a plan exists); `what_next_covered` required iff evidence present
AND `what_next_allowed` (else `NOT_APPLICABLE`, never penalized); `uncertainty_covered` required
iff `uncertainties` evidence exists OR `source_sufficiency` ∈ {PARTIAL, HEADLINE_ONLY,
CONFLICTING}; `safe_length_compliance`/`structure_adequate` required iff a length/paragraph plan
is available, else `NOT_APPLICABLE` (never fabricated from nothing — `tests/test_editorial_
completeness.py::test_backward_compatibility_without_m1_data`/`test_compatibility_without_m3_m4_
plans`).

## 8. Evidence matching

`services/text_normalization.py`: NFKC + casefold + guillemet/quote stripping (`«»""''`) + dash
normalization, plus a conservative, explicit Russian case-suffix stripper (`strip_ru_case_suffix()`
— a fixed ~25-ending list, skipped for tokens ≤4 chars or ALL-CAPS, never a general morphological
analyzer). `fuzzy_phrase_contains()` is whole-word-normalized containment (never a short raw
substring match). `token_overlap_ratio()` is used only as one input signal, never the sole basis
for a verdict — M0's own disclosed mistake. Coverage checking
(`_coverage_ratio()`) tries claim-level matching (numeric/date/entity/quote, reusing
`services.fact_safety.extract_claims`) **OR** a ≥40% token-overlap fallback — fixed mid-milestone
after the real backtest showed the claims-only path missing genuine matches when a multi-word
entity extraction fragmented slightly differently between the brief text and the draft body (§20).

## 9. Headline-rewrite detection

`assess_headline_rewrite_risk()` (§ replacing M0's 0%-effective proxy): counts genuinely NEW
claims the body adds beyond the title (via `extract_claims`, not vocabulary overlap) plus
editorial-framing signals (uncertainty/why-it-matters/what-next markers). Any new checkable claim
→ `LOW`; no new claim but real framing added → `MEDIUM`; neither, with high title/body token
overlap → `HIGH`. A `HEADLINE_ONLY`/`EMPTY` source always returns `NOT_APPLICABLE` — never
penalized for lacking facts it structurally cannot have (real M4.1 evidence, `d9c0b32c`/
`073437a9`, showed the deciding factor there was honest framing, not source thinness).

## 10. Source-sufficiency handling

`source_sufficiency` is read from `EditorialBrief` first, `AdaptiveLengthPlan` second, else
`UNKNOWN` — never invented. `HEADLINE_ONLY`/`EMPTY` routes straight to `INSUFFICIENT_SOURCE` in
the recommendation logic (§11) ahead of every other check except a genuine Fact Safety `FAIL` or
`HIGH` rewrite risk, so a thin source with an honest, minimal draft is never scored a false
`NOT_READY`.

## 11. Editorial recommendation logic

Priority order (`_recommendation()`): (1) thin source + fact-safety-not-FAIL + rewrite-risk-not-
HIGH → `INSUFFICIENT_SOURCE`; (2) calibrated Fact Safety `FAIL` → `NOT_READY`; (3) main-fact or
event-details required `FAIL`, or rewrite risk `HIGH`, or filler/repetition present → `NOT_READY`;
(4) any other required `FAIL` → `REVIEW`; (5) any required `PARTIAL`, or calibrated Fact Safety
`REVIEW`, or `PARTIAL` source → `REVIEW`; (6) else `READY`. Always explainable via
`reason_codes` back to the specific criterion/flag that decided it.

## 12. Raw Fact Safety behavior

`services/candidate_fact_safety.py`'s `evaluate_candidate_fact_safety()` is used completely
unmodified as the raw layer, exactly per this milestone's own instruction — never rewritten,
never re-implemented.

## 13. Known false-positive classes (confirmed on real data)

From M4.1 (§3): Russian declension against Research's own paraphrase (`fa60525c`); a definition-
flag fragment of a real, longer supported entity (`7352db1a`, "Corporation" from "United
Microelectronics Corporation"); a hedge/epistemic-limitation sentence misclassified as an
unhedged causal claim (`7352db1a`, "...оснований нет"); a qualitative-synthesis sentence
misclassified as an unhedged forecast despite introducing no new checkable claim.

## 14. Calibration rules

`services/fact_safety_calibration.py::calibrate_fact_safety()`, four named suppression rules, each
with its own reason code, applied only to specific flag categories:
1. `russian_inflection_or_quote_match` — **only** on `unsupported:` flags (never `uncertain:` —
   an `uncertain:` flag already reflects Phase 15 M5's own deliberate "Research-only match stays
   uncertain, never upgraded to safe" policy; suppressing it would override that intentional
   design, not fix a bug). Checks the flagged claim against source **+ Research's own facts**
   (`research_facts`) using case-suffix-aware matching.
2. `definition_fragment_of_supported_entity` — a `definition_flag` term found as part of a longer
   capitalized phrase in the real source text (covers company-legal-suffix words as one instance,
   never a special case).
3. `hedge_language_misclassified` — a `causal_connector`/`unhedged_forecast` flag whose own
   sentence contains an epistemic-limitation phrase ("нет оснований", "нельзя утверждать", etc.).
4. `qualitative_synthesis_no_new_checkable_claim` / `confirmed_fact_synthesis` — an
   `unhedged_forecast` flag whose sentence introduces no claim of its own, or whose every claim
   already matches the source (a confirmed synthesis, not an invented prediction).

A survivor is filed as `true_positive_flags` (numeric/entity/definition — never downgraded) or
`unresolved_flags` (causal-family only — the raw module's own disclosed "flag for review, not a
verification" category), never silently dropped.

**Corrected during implementation**: an early version also escalated a *central* unsupported
entity flag to `FAIL` — removed after the real 269-baseline backtest showed this made calibration
a net *increase* in FAIL count (32→47) versus the raw audit, contradicting the raw module's own
deliberate design (only money/percentage/date/quote-type unsupported claims escalate to FAIL;
entity claims are always REVIEW-tier at most, regardless of centrality). After the fix, calibrated
FAIL count on the same 269 baseline is 4 (§20) — a real, measured reduction, not a regression.

## 15. False-negative safety

`tests/test_fact_safety_calibration.py` includes 9 explicit regression fixtures verifying flags
that must survive calibration unchanged: unsupported number/percentage/date, unsupported entity,
unsupported company description, unsupported causal claim (no hedge), unsupported definition,
market-leader claim, and a forecast naming a genuinely new unevidenced number. All 9 pass.

## 16. Shadow integration

`editorial_completeness_mode: Literal["off", "shadow"] = "off"` in `core/config.py`. New
`CapabilityExecutor._attach_editorial_completeness()`, called only for `step.capability ==
"quality"`, only when mode is `"shadow"`. Builds a fresh `CandidateFactSafetyAudit` +
`CalibratedFactSafetyAssessment` directly from `research`/`copywriting` step_results (zero new
DB query), then `apply_editorial_completeness_shadow()` (purely additive merge, mirrors
M1-M4's own established convention exactly).

## 17. Failure isolation

Wrapped in try/except exactly like every M1-M4 attach method — any exception is logged
(`completeness_assessment_failed`) and swallowed, `structured_output` returned completely
unchanged, the "quality" step still reaches `SUCCESS`
(`tests/test_phase17_m5_integration.py::test_shadow_failure_isolation`, verified by monkeypatching
`evaluate_candidate_fact_safety` to raise).

## 18. Backtest datasets

All read-only, zero LLM calls, zero mutation (`scripts/phase17_m5_completeness_gate_backtest.py`):
**269/269** production baseline drafts (the full pinned M0 sample, not just the 100 minimum),
**32/32** saved M3 candidates, **32/32** merged M4/M4.1 candidates. `EditorialBrief`/
`AdaptiveLengthPlan`/`BeginnerFriendlyPlan` rebuilt fresh, read-only, from each case's own already-
persisted `research`/`intelligence` step_results — never regenerated, never mutated.

## 19. Baseline results (269 cases)

`editorial_recommendation`: REVIEW 178 (66.2%), NOT_READY 65 (24.2%), INSUFFICIENT_SOURCE 26
(9.7%), READY 0. `headline_rewrite_risk`: LOW 180 (66.9%), MEDIUM 59 (21.9%), NOT_APPLICABLE 26
(9.7%), HIGH 4 (1.5%) — a real, working, non-zero HIGH-risk signal where M0's own proxy measured
0%. `completeness_score`: mean 0.680, median 0.682. Raw Fact Safety: pass 85 / review 152 / fail
32. **Calibrated: pass 110 / review 155 / fail 4** — FAIL count cut from 32 to 4 (87.5% reduction).
Missing-criterion rates (of applicable cases): headline_fact 23.8%, event_details 7.1%, subject_
explanation 26.5%, why_it_matters 21.9%, uncertainty 20.5%; background_context 0/0 applicable
(`build_editorial_brief()`'s own background_context field is populated in none of these 269 cases
— a pre-existing M1 limitation, not new here).

## 20. M3 results (32 cases)

REVIEW 24 (75.0%), INSUFFICIENT_SOURCE 6 (18.75%), NOT_READY 2 (6.25%), READY 0.
completeness_score mean 0.820, median 0.833. Raw Fact Safety: fail 4 / pass 5 / review 23.
**Calibrated: fail 1 / pass 8 / review 23** — FAIL cut from 4 to 1 (75% reduction).

## 21. M4/M4.1 results (32 cases)

REVIEW 22 (68.75%), INSUFFICIENT_SOURCE 6 (18.75%), NOT_READY 4 (12.5%), READY 0.
completeness_score mean 0.862, median 0.869 — the highest of the three datasets, consistent with
M4.1's own already-disclosed 96.9% preferred-or-tied-vs-M3 finding. Raw Fact Safety: fail 3 / pass
4 / review 25. **Calibrated: fail 1 / pass 7 / review 24** — FAIL cut from 3 to 1 (67% reduction);
the one remaining calibrated FAIL is `eae93502` (§13/§25, a different, out-of-scope money-range
parsing gap, not a new calibration miss).

## 22. Gold-set evaluation

96 labeled cases (32 pinned draft_ids × baseline/M3/M4, well above the 32-case minimum) —
`scripts/_phase17_m5_manual_gold_set.json`. Labels are a documented, deterministic derivation from
already-recorded real human judgments (M0's own disclosed headline-rewrite/WEAK list, M1's own
`source_sufficiency` classification, M3's/M4's own manual A/B/C quality+preference verdicts, and
M4.1's own manual review of the 7 replayed cases + its 2 disclosed Fact Safety corrections) —
never a fresh blind re-read, never silently overwriting any prior verdict (a genuinely new label
dimension). **Overall accuracy: 77.1% (74/96)**. Per-variant accuracy: baseline 75.0%, M3 81.25%,
M4 75.0%.

## 23. Completeness confusion matrix

| gold \\ predicted | INSUFFICIENT_SOURCE | NOT_READY | REVIEW |
|---|---|---|---|
| INSUFFICIENT_SOURCE | 18 | 0 | 0 |
| NOT_READY | 0 | 0 | 4 |
| READY | 0 | 1 | 8 |
| REVIEW | 0 | 9 | 56 |

**False READY rate: 0% (0 predicted)** — the primary acceptance target, met exactly (there is no
case where the gate said READY and gold disagreed, because the gate never said READY at all in
this backtest). **False NOT_READY rate: 100% (10/10 predicted)** — fails the ≤10% target
significantly; every `NOT_READY` prediction in this sample corresponded to a gold `REVIEW` or
`READY`, never a gold `NOT_READY`. `READY` recall: 0/9 (the gate never reaches READY on this
sample). Root cause, read directly from the 10 false-`NOT_READY` cases: 6/10 are
`main_fact_not_covered` (a strict entity/claim mismatch between `EditorialBrief.headline_fact`
and a short baseline draft — softened once during this milestone via the token-overlap fallback,
§8, but not fully resolved), 3/10 are `eae93502`'s own already-disclosed, out-of-scope Fact Safety
false positive (§13/§25) recurring across all three of its variants, 1/10 is a `filler_or_
repetition_present` flag on an M4 case worth a closer look in a future tuning pass.

## 24. Raw vs. calibrated Fact Safety metrics

| Dataset | Raw fail | Calibrated fail | Reduction |
|---|---|---|---|
| Baseline (269) | 32 | 4 | 87.5% |
| M3 (32) | 4 | 1 | 75.0% |
| M4/M4.1 (32) | 3 | 1 | 66.7% |

Gold-set Fact Safety accuracy (96 cases): **86.5%** (confusion matrix: of 67 gold-REVIEW cases, 61
predicted REVIEW correctly; of 26 gold-PASS, 20 correct; of 5 gold-FAIL — the 2 known M4.1 cases ×
their applicable variants plus `eae93502` — 2 correctly predicted FAIL, 2 downgraded to REVIEW, 1
to PASS). True-positive retention on the 9 explicit regression fixtures (§15): **100%**. False
negatives on those fixtures: **0**.

## 25. Known regression cases

Both M4.1-disclosed false positives (`fa60525c`, `7352db1a`) are confirmed fixed by calibration on
the real merged M4 data (§21). `eae93502` (M4's own §26 disclosure) remains an unresolved FAIL
after calibration — a money-*range* parsing gap ("$1-2 млрд" partially matching "2 млрд") in the
underlying `services/fact_safety.py` extractor, not one of this milestone's named calibration
targets; disclosed here rather than silently left unexplained.

## 26. Tests

76 targeted M5 tests, all passing: 43 in `tests/test_editorial_completeness.py` (schemas,
14 completeness criteria, headline-rewrite risk, recommendation logic), 20 in `tests/test_fact_
safety_calibration.py` (suppression rules + 9 false-negative-safety regression fixtures), 13 in
`tests/test_phase17_m5_integration.py` (shadow mode, failure isolation, production-output byte-
identity, no ContentDraft/task-state mutation, no Telegram, no LLM, backward compatibility without
M1/M3/M4 data, idempotency, safe logging). Ruff and Mypy clean on all 11 changed/added files.
`scripts/validate_architecture.py`: 0 forbidden-dependency violations. Pre-existing M1-M4.1
regression suites (`test_adaptive_length.py`, `test_beginner_friendly.py`, `test_editorial_
brief.py`, `test_channel_relevance.py`, `test_fact_safety.py`): 230 passed, 2 failed — both
pre-existing baseline failures (`test_fact_safety.py::test_off_mode_...`/`test_shadow_mode_...`,
a DB-row-count assertion sensitive to full-suite execution order, present in the confirmed pre-M5
baseline too, not a new regression).

## 27. Known limitations

- **0/32 candidates reach READY in any backtest dataset** — the gate is conservative by design
  (calibrated Fact Safety PASS on only 7-8 of 32 candidates per dataset, plus safe-range
  compliance genuinely at ~59% per M4.1's own disclosed figure), producing zero false READY but a
  measured 100% false NOT_READY rate on a 10-case subset (§23) — the acceptance target this
  milestone did **not** meet. Root cause is a mix of a real, still-imperfect evidence-matching gap
  (§8/§23) and the underlying Fact Safety REVIEW-tier being reached often (uncertain: entity
  mentions correctly kept "uncertain" per Phase 15 M5's own deliberate design, §14).
- `eae93502`'s money-range parsing gap remains unresolved (§25) — out of scope, not attempted.
- `background_context_covered` is `NOT_APPLICABLE` for all 333 backtested cases across all three
  datasets — `services/editorial_brief.py`'s own `background_context` builder rarely/never
  populates this field on real data, a pre-existing M1 limitation inherited, not a new one.
- Multi-word entity extraction fragmentation (M4's own §25) still affects coverage matching in
  some cases even after the token-overlap fallback (§8) — a narrow, disclosed limitation of the
  shared `extract_claims()` regex, not rebuilt here (out of scope, "не создавай universal NLP
  engine").

## 28. Production activation decision

**Not activated.** `editorial_completeness_mode` defaults to `"off"`; no production prompt,
routing, or worker behavior changed. Given the §23/§27 false-NOT_READY gap, this milestone's own
verdict is **SHADOW READY — TUNING REQUIRED**, not VALIDATED — matching this project's own
established discipline (M0, M4) of disclosing a real, measured shortfall rather than rounding up.

## 29. M6 handoff

M6 (Integrated Editorial Validation) should treat `EditorialCompletenessAssessment`/
`CalibratedFactSafetyAssessment` as one of several inputs to its own `IntegratedEditorialValidation`
decision — never assume M5's own `editorial_recommendation` is production-grade on its own. The
§23 false-NOT_READY gap should inform M6's own decision-policy design (e.g., M6 may need its own,
less literal-evidence-matching-dependent completeness signal, or M5's coverage matching should get
a follow-up tuning pass before M6 relies on it heavily for the same purpose).

## 30. Definition of Done

- [x] Versioned completeness + calibrated Fact Safety schemas created, no mutable defaults.
- [x] Gate evaluates required + optional criteria, all 14 specified.
- [x] Source sufficiency handled; thin sources never produce a false `NOT_READY`.
- [x] Headline-rewrite detection replaced (0% proxy → real, measured HIGH/MEDIUM/LOW signal).
- [x] READY/REVIEW/NOT_READY/INSUFFICIENT_SOURCE implemented, explainable via reason_codes.
- [x] Raw and calibrated Fact Safety kept separate; raw audit never modified.
- [x] Known M4.1 false positives (`fa60525c`, `7352db1a`) fixed and confirmed on real data.
- [x] True-positive regression fixtures preserved (100% retention, 0 false negatives, 9 fixtures).
- [x] Shadow mode never changes production output/ContentDraft/task state/Telegram; 0 LLM calls.
- [x] 269 baseline + 32 M3 + 32 M4 candidates backtested (exceeds all stated minimums).
- [x] 96 gold-labeled cases (exceeds the 32-case minimum), completeness + Fact Safety metrics computed.
- [x] 76 targeted tests passing; Ruff/Mypy/architecture validation clean.
- [ ] **False NOT_READY rate ≤10%** — NOT met (measured 100% on a 10-case subset, §23/§27) — the
      one acceptance target this milestone discloses as unmet, driving the TUNING REQUIRED verdict.
- [x] Report created; checkpoint `checkpoint/phase17-m5` to follow this report's own commit.
- [x] Production workers remained stopped throughout (confirmed at the start of this milestone).
