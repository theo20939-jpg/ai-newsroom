# R2.10G3-E1 — Production-Shaped Shadow Eventness Rejectors — Final Report

Production code changed in this phase (explicitly authorized, §3) — but strictly SHADOW-ONLY:
zero DB writes, zero LLM calls, zero Telegram, zero publication changes, zero readiness mutation.
Not merged into `feature/phase19-editorial-depth-upgrade`. Not deployed. Not enabled anywhere.

## A. Base

```text
BASE_COMMIT=cdf14aa9d26a120d9d139e396d3aa044606c9622  (G3-D: G3_ONLY_SUBSET_OF_REJECTORS_REMAINS_SAFE)
BRANCH=feature/r2-10-g3-eventness-shadow-wiring
FILES_CHANGED=5  (core/config.py, services/event_recap.py,
  scripts/_recap_r2_10_readiness_candidate_scanner.py [modified];
  services/recap_eventness_shadow.py, tests/test_recap_eventness_shadow.py [new])
```
`services/recap_event.py` is explicitly UNCHANGED (verified: empty diff against base) — an earlier
wiring attempt there was reverted once inspection showed `build_recap_event_snapshot()` is not the
code path the real scanner/pipeline actually uses; `services/event_recap.py::build_event_recap_
candidate()` is (§13's own "before implementation inspect... choose a single canonical location"
requirement, taken seriously rather than wiring into the first plausible-looking function).

## B. Shadow implementation

```text
SHADOW_HELPER=services/recap_eventness_shadow.py::evaluate_eventness_shadow()
SHADOW_FLAG=core.config.settings.recap_eventness_shadow_enabled
DEFAULT=false
READINESS_MUTATION=false
```
`EventnessShadowFeatures`/`EventnessShadowEvaluation` are plain frozen dataclasses; the evaluator
is a pure function (no DB, no network, no side effects). Wired into `build_event_recap_candidate()`
strictly AFTER `readiness`/`clusters`/`unique_sources` are already fully computed and used - the
shadow block reads those same already-finalized values, never recomputes or influences them.
Carried through to `EventRecapCandidate.eventness_shadow` (new, additive, default `None`) and to
the read-only scanner's `CandidateScanRow.eventness_shadow` (§19).

## C. Rule definitions

```text
RULE_A_IMPLEMENTED=true   (span_hours>=200 AND unique_source_count<=1 AND announcement_count>=4)
RULE_C_IMPLEMENTED=true   (source_domains == {'github.com'} exclusively)
RULE_D_IMPLEMENTED=false  (verified: no RULE_D-shaped identifier anywhere in the shadow module or
  either of its two wiring sites - test_rule_d_implementation_does_not_exist_anywhere_in_
  production_code, AST-based, not a naive substring check)

OFFLINE_PRODUCTION_PARITY=100% (RULE_A and RULE_C both, across 84 real fixtures resolved from the
  ~90-fixture consolidated labelled corpus in this DB - see D below)
```
**Boundary-operator disclosure (§6):** this module reproduces G3-B's own ACTUAL, validated `RULE_A`
implementation verbatim — `story_span_hours >= 200.0` (not a strict `>`). §6's own prose elsewhere
restates the rule as "story_span_hours > 200," but §6 also says "No >=200 change" and "must
reproduce G3-B/G3-D behavior exactly" — reproducing the real, 0-false-reject-validated `>=`
behavior is the safe reading; switching to strict `>` would itself be an unvalidated behavioral
change. Disclosed explicitly (`test_rule_a_boundary_at_exactly_200h`'s own docstring), not silently
picked.

## D. Corpus replay

```text
LABELLED_STORIES_REPLAYED=84  (of ~90 in the consolidated corpus - 6 fixtures are offline-only,
  i.e. have no story_id to look up in this DB, so are outside this specific replay's own scope;
  they were already covered by G3-B's own calibration)
RULE_A_TRIGGER_COUNT=matches G3-B/G3-D exactly on every one of the 84 (0 discrepancies)
RULE_C_TRIGGER_COUNT=matches G3-B/G3-D exactly on every one of the 84 (0 discrepancies)

RULE_A_COUNTERFACTUAL_FALSE_REJECTS=0
RULE_C_COUNTERFACTUAL_FALSE_REJECTS=0
```
No actual rejection was ever performed (§15) — this is the production shadow evaluator's own
trigger verdict compared against the offline G3-B rule functions on the same fixtures, read-only,
counterfactual only.

## E. Rule A DB audit

```text
DB_MATCHES=10  (fresh, live scan - 938 Stories with event_count>=1, event_count>=1 window)
MANUALLY_REVIEWED=10 (all 10)
REAL_EVENT_COUNTEREXAMPLES=0

RULE_A_CANDIDACY=PRODUCTION_CANDIDATE
```
All 10 live matches are ALREADY-LABELLED fixtures from G3-A/G3-B/G3-D (7 TOPIC_CLUSTER, 2 DIGEST,
1 NOISE) — zero new, unexamined Rule A triggers exist in the current DB, and zero are a genuine
real event/lifecycle. No long-running real lifecycle, rolling incident, legal timeline, conference
series, or open-source release cycle was found matching Rule A's shape. RULE_A_CANDIDACY is
reaffirmed, unrevoked.

## F. Rule C DB audit

```text
DB_MATCHES=63  (same live scan)
MANUALLY_REVIEWED=63 (titles) + 6 (full URL verification)
GITHUB_REAL_EVENT_COUNTEREXAMPLES=6 (confirmed by real URL inspection)

RULE_C_CANDIDACY=REVOKED
```
**This is the central finding of this phase.** Most of the 63 matches are PyTorch CI/build-bot
noise (the same pattern as `ciflow_ci_noise`) or bare numeric build tags ("b10737," "b10738," ...)
- genuinely non-editorial. But real URL inspection of the more distinctive titles found **6
confirmed real GitHub-only editorial events**:

| Story | Real URL | What it is |
|---|---|---|
| "Janet 1.42.0" | github.com/janet-lang/janet/releases/tag/v1.42.0 | A real open-source programming-language release |
| "Hi HN, we're Brandon and Kingston..." | github.com/Hebbian-Robotics/hflow | A real Show-HN startup/product launch |
| "Vermell – Minimal, dependency-free C++ web framework..." | github.com/vermellcc/vermell | A real open-source project launch |
| "RotaryCell: Making an unmodified rotary phone work over LTE..." | github.com/fregacmols/RotaryCell | A real maker/Show-HN project |
| "I built FnScribe because..." | github.com/AlgorithmicResearchGroup/fnscribe | A real personal open-source tool launch |
| "bibliograph: An AppView for..." | github.com/olamaelcu/bibliograph | A real open-source project |

§16's own explicit instruction applies directly: "If any real GitHub-only event is found:
RULE_C_CANDIDACY=REVOKED." Rule C's own threshold/logic is UNCHANGED (§16: "do not change Rule
C") — only its candidacy status is downgraded. The diagnostic code is kept (§16: "keep diagnostic
code if useful") since it remains valid, harmless, shadow-only evidence for future work (e.g. a
possible future refinement distinguishing CI-bot/build-tag noise from genuine Show-HN-style
GitHub content — explicitly NOT attempted in this phase, since §7 forbids adding a
whitelist/blacklist/special-case here).

## G. Mandatory controls

```text
VLA=RULE_A triggered (correct - reproduces G3-A/G3-B/G3-D exactly)
NVIDIA_HF=neither RULE_A nor RULE_C triggered (correct - never falsely flagged)
CI_NOISE=RULE_C triggered (correct - reproduces G3-A/G3-B/G3-D exactly; ALSO triggers RULE_A,
  a new observation from this phase's own live audit - ciflow_ci_noise's own span/announcement
  shape happens to independently satisfy both rules' conditions, consistent since both rules
  agree REJECT is the right diagnostic signal for this fixture)
SHORT_MULTI_SOURCE_REAL_EVENTS=g3d_pixel11_fold_embargo/g3d_apple_sept9_event/g3d_microsoft_
  copilot_merge (the 3 RULE_D false-reject fixtures) - confirmed NEITHER RULE_A NOR RULE_C
  triggers on any of them (verified via test_rule_d_shape_produces_no_signal and the full corpus
  parity test) - RULE_D's own absence from this module means none of these are flagged.
```

## H. Readiness parity

```text
SHADOW_OFF=baseline (readiness_state/readiness_overridden/story_integrity_eligible/story_
  integrity_reasons/announcement_count/readiness_source_count/evidence_reference_count/
  publishable/source_refs)
SHADOW_ON=byte-identical on every one of the above fields (test_shadow_flag_off_and_on_produce_
  identical_readiness) - only `eventness_shadow` itself differs (None -> populated)

READY_DELTA=0
COOLING_DELTA=0
REJECTED_DELTA=0
```
Also verified on a natural-rejection path (VLA, not force-shadow-eligible): `rejected`/
`rejection_reasons` are identical with the flag OFF vs ON (test_shadow_on_never_touches_
rejection_reasons_or_publishable).

## I. Tests

```text
SCOPED_TESTS=
  19 new (tests/test_recap_eventness_shadow.py) - includes the offline/production parity test
    across the consolidated ~90-fixture corpus
  19/20 G3-D (1 EXPECTED, classified non-regression - see below)
  26/27 G3-C (1 EXPECTED, classified non-regression - see below)
  19/19 G3-B calibration
  20/20 G3-A harness
  141/141 recap_event + event_recap
  6/6 scanner (tests/test_recap_r2_10_readiness_candidate_scanner.py)
  TOTAL: 250 passed, 2 expected/classified failures, 0 real regressions
RUFF=clean (all 5 touched files)
MYPY=clean (all 4 touched production files)
```
**Classified non-regression failures:** G3-C's and G3-D's own `test_no_production_files_changed_
since_base_commit` tests each fail with the same message: `production/forbidden paths changed:
['core/config.py', 'services/event_recap.py', 'services/recap_eventness_shadow.py']`. This is
EXPECTED, not a regression - those tests check the working tree against THEIR OWN phase's base
commit and allowed-prefix contract (scripts/tests/docs/prompts only, since G3-C/G3-D were
explicitly shadow-research-only phases). This phase (E1) is the first explicitly authorized to
touch production code (§3) - a later, wider-scoped phase naturally trips an earlier, narrower
phase's own scope-check test. Neither test file was modified (both remain frozen historical
artifacts); every other test in both suites (19/20 and 26/27 respectively) passed without issue,
confirming no actual behavioral regression in either phase's own validated logic.

## J. Safety

```text
DB_WRITES=0
LLM_CALLS=0
TELEGRAM_SENDS=0
PUBLICATION_CHANGES=0
DOCKER_ACTIONS=0
DEPLOYMENTS=0
```
Verified structurally (`test_shadow_module_imports_no_llm_gateway` - the shadow module imports
nothing beyond `dataclasses`/`typing`/`__future__`; `test_no_eventness_driven_mutation_in_wiring_
sites` - no line combining `eventness_shadow` with a mutation keyword in either wiring site) and
empirically (`test_shadow_evaluation_writes_no_db_rows` - real Story/EditorialTask row counts
unchanged). `recap_eventness_shadow_enabled` defaults `False` and is not set to `true` anywhere in
this repository outside test monkeypatches (`test_shadow_flag_defaults_false_and_is_enabled_
nowhere_in_repo_config`, §27).

## K1. LLM policy (frozen, unchanged from G3-C/G3-D — §22/§23)

```text
LLM_AUTO_REJECT_ALLOWED=false
LLM_AUTO_ACCEPT_ALLOWED=false
LLM_SHADOW_ONLY=true
HUMAN_REVIEW_RECOMMENDED=true
```
No LLM code, prompt, or Gateway import was added, copied, or referenced anywhere in this phase's
production changes (`test_shadow_module_imports_no_llm_gateway`). No human-review workflow, UI, DB
table, or Telegram control was built (§23) — the design conclusion from G3-C/G3-D (LLM advisory
only, human review likely required for the hard middle) is preserved as a recorded decision only,
not implemented.

## K. Commit

```text
COMMIT_CREATED=<see final message>
COMMIT_SHA=<see final message>
FILES_IN_COMMIT=<see final message>
```
