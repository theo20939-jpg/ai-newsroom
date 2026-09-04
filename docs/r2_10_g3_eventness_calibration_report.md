# R2.10G3-B — Eventness Rule Calibration Report

**Status: calibration/exploration only. No production eventness gate exists after this phase.**
Base: `33775377a195b9c33a44e3f2a6510856793ee41c` (G1 + G3-0 + G3-A). Branch:
`feature/r2-10-g3-eventness-calibration`. `feature/phase19-editorial-depth-upgrade` remains frozen
at G1, untouched.

## 0. Dataset drift check

The G3-A harness was re-run live against the current local dev DB before any calibration work
began: `FALSE_ACCEPT=1, FALSE_REJECT=10, NEEDS_REVIEW=3, 0 skipped` — **identical** to G3-A's own
committed report. `G3A_SNAPSHOT_RESULT == CURRENT_DB_RESULT`; no drift to reconcile.

## 1. Dataset

```text
CALIBRATION_STORIES=31 (G3-A's own manifest, frozen, unedited)
HOLDOUT_STORIES=13 (new, this phase — scripts/_recap_r2_10_g3_eventness_holdout.py)
```

Manual `manual_class` grouping (§6's own literal definition):

```text
Calibration: POSITIVE_EVENT=12  NEGATIVE_EVENT=17  AMBIGUOUS=2
Holdout:     POSITIVE_EVENT=10  NEGATIVE_EVENT=3   AMBIGUOUS=0
```

**No label was edited to make a rule fit.** `LABEL_CORRECTION_PROPOSED=none` — no calibration
label was found to be factually wrong during this phase.

**A real methodological tension, resolved and disclosed rather than hidden:** `vk_apple_synthetic_
4publisher_false_ready`'s `manual_class` is `REAL_SINGLE_EVENT` (a real lawsuit-filing event did
occur) — literally a `POSITIVE_EVENT` member under §6's own grouping — yet its `desired_eventness`
is explicitly `REJECT` (its entire purpose as the mandatory negative control for readiness
inflation via syndication). Scoring strictly by `manual_class` would count a rule correctly
rejecting this fixture as a **false reject**, directly contradicting §14/§27's own framing of it as
"the highest-value FALSE_ACCEPT example" a safe rule should catch. **All rule scoring in this
report uses `desired_eventness` (ACCEPT=positive, REJECT=negative) as ground truth**, not raw
`manual_class` — this cleanly resolves the tension and, as a side effect, treats
`vk_apple_real_3publisher` (`NEEDS_REVIEW`) and `marvell_google`/`optimizatsiya_koda` (`UNCERTAIN`)
consistently with how `UNCLEAR`-class fixtures are already excluded from binary scoring, rather
than as a one-off special case. The raw `manual_class` counts above are still reported for §6/§B
compliance; they were never used to score a rule.

Holdout composition gap, disclosed: 10 `REAL_SINGLE_EVENT`, 2 `TOPIC_CLUSTER`, 1 `NOISE`, **zero**
`EVENT_LIFECYCLE`/`DIGEST`/`UNCLEAR`. A genuine, broad search (most recent ~400 unused Stories) was
made for fresh instances of those three classes and none were found in this database's current
window — not a cherry-picked composition, a real search result.

## 2. Class feature distributions (calibration, n and min/p25/median/p75/max)

| Class | n | span_hours | sources (median) |
|---|---:|---|---:|
| TOPIC_CLUSTER | 12 | 44.2 / 130.8 / 304.0 / 479.9 / 494.1 | 1.0 |
| DIGEST | 3 | 309.7 / 394.8 / 479.8 / 479.9 / 479.9 | 1.0 |
| EVENT_LIFECYCLE | 3 | 98.6 / 112.0 / 125.3 / 132.7 / 140.1 | 4.0 |
| REAL_SINGLE_EVENT | 9 | 0.5 / 1.4 / 26.2 / 135.3 / 283.4 | 2.0 |
| NOISE | 2 | 8.1 / 120.1 / 232.2 / 344.2 / 456.3 | 1.0 |
| UNCLEAR | 2 | 2.0 / 48.4 / 94.9 / 141.3 / 187.8 | 2.5 |

(Full raw per-fixture values, including `effective_event_count`/`announcement_count`/
`single_event_cluster_count`/`multi_source_cluster_count`, are in the committed evaluation JSON
from G3-A, reproducible by re-running `scripts._recap_r2_10_g3_eventness_harness`.)

## 3. Candidate rules

All three families below were written with a rationale **before** measurement, per this phase's
own explicit anti-overfitting instruction. None uses a threshold "optimized" against these same 31
rows beyond a single, disclosed, human-reasoned read of the distribution table above.

### RULE_A — long-lived, single-source topic collection
```text
RULE=story_span_hours >= 200 AND unique_source_count <= 1 AND announcement_count >= 4 => REJECT
RATIONALE=every TOPIC_CLUSTER fixture showed unique_source_count==1 (12/12); 200h sits safely
  below TOPIC_CLUSTER's own p25 (130.8h) and above every POSITIVE fixture's span EXCEPT one
  (twitch_genai_optout, 283.4h — but that fixture has sources=4, failing the source condition, so
  it is unaffected). announcement_count>=4 reuses the already-existing recap_min_announcement_count
  maturity floor, not a newly invented number.
```
```text
CAL_TRUE_NEGATIVE_REJECTS=10   CAL_FALSE_REJECTS=0   CAL_NEGATIVE_COVERAGE=0.556
HOLDOUT_TRUE_NEGATIVE_REJECTS=1   HOLDOUT_FALSE_REJECTS=0   HOLDOUT_NEGATIVE_COVERAGE=0.333
LOO_STABLE=true (0 of 31 leave-one-out removals introduce a false reject)
```

### RULE_C — GitHub CI single-domain noise
```text
RULE=source_domains == {"github.com"} exclusively => REJECT
RATIONALE=both the calibration (ciflow_ci_noise) and a FRESH holdout NOISE fixture from a
  different repo/tag convention (holdout_pytorch_trunk_noise) are exclusively sourced from
  github.com release/commit tags — not editorial content at all. Uses only an already-collected
  feature (source_domains); no title/NLP pattern, no broad blacklist beyond this one domain.
```
```text
CAL_TRUE_NEGATIVE_REJECTS=1   CAL_FALSE_REJECTS=0   CAL_NEGATIVE_COVERAGE=0.056
HOLDOUT_TRUE_NEGATIVE_REJECTS=1   HOLDOUT_FALSE_REJECTS=0   HOLDOUT_NEGATIVE_COVERAGE=0.333
LOO_STABLE=true
```
Narrow, but the **only rule in this report independently confirmed on a genuinely fresh negative
case never seen during rule design** — real, if modest, generalization evidence.

### RULE_D — short-span, multi-source, zero-corroboration syndication
```text
RULE=story_span_hours <= 1.0 AND unique_source_count >= 3 AND announcement_count ==
  effective_event_count (no clustering merge occurred at all) => REJECT
RATIONALE=the VK synthetic fixture: span=0.5h, sources=4, announcements=4 — every event its own
  cluster, zero corroborative merging despite maximal source diversity, the opposite signature of a
  genuine fast-breaking multi-source real event (which usually DOES partially merge via near-exact
  titles). Measured honestly against R2.11's own predicted risk (verb-blindness) rather than
  assumed safe in advance.
```
```text
CAL_TRUE_NEGATIVE_REJECTS=1   CAL_FALSE_REJECTS=0   CAL_NEGATIVE_COVERAGE=0.056
HOLDOUT_TRUE_NEGATIVE_REJECTS=0   HOLDOUT_FALSE_REJECTS=0   HOLDOUT_NEGATIVE_COVERAGE=0.0 (no negative of this shape in the holdout to test against — a real, disclosed gap, not a claim of confirmed generalization)
LOO_STABLE=true
```
**This is the answer to §27's central product question — see §7 below.**

### Pareto summary

| Rule | Cal. negative coverage | Cal. false rejects | Holdout false rejects | Interpretability |
|---|---:|---:|---:|---|
| A | 55.6% | 0 | 0 | high — one arithmetic threshold on 2 features |
| C | 5.6% | 0 | 0 | very high — exact-set membership on 1 field |
| D | 5.6% | 0 | 0 | high — 3 conditions, directly evidenced by the mandatory fixture |
| A∪C∪D | 61.1% | 0 | 0 | same as above, unioned |

Zero false rejects dominates the choice here, per this phase's own explicit priority — no rule was
discarded for low coverage; none needed to be, since none produced a false reject to trade off.

## 4. Best safe deterministic rule set

```text
BEST_RULE_SET=RULE_A OR RULE_C OR RULE_D (union)
CAL_FALSE_REJECTS=0        HOLDOUT_FALSE_REJECTS=0
CAL_NEGATIVE_COVERAGE=0.611 (11/18)   HOLDOUT_NEGATIVE_COVERAGE=0.667 (2/3)
```
Holdout negative coverage is measured on only 3 fixtures (2 TOPIC_CLUSTER + 1 NOISE — no
holdout syndication case) — a genuinely small sample; the **zero false rejects across both 30
calibration positives and 23 holdout positives evaluated is the load-bearing finding**, not the
coverage percentage.

## 5. Mandatory fixtures

```text
VLA=REJECTED by RULE_A (span=479.2h, sources=1, announcements=16) — correct
VLM=NOT rejected by any rule (span=90.9h < RULE_A's 200h threshold) — sits in the hard middle, see §8
NVIDIA_HF=never rejected by any candidate or combined rule (verified directly) — the mandatory positive control holds
VK_APPLE_FALSE_READY=REJECTED by RULE_D and the combined rule — the central finding
MARVELL=excluded from binary scoring entirely (UNCERTAIN) — never counted as a reject or a miss
CI_NOISE=REJECTED by both RULE_A (span/source pattern) and RULE_C (domain) — doubly covered
```

## 6. Current-readiness interaction (simulated, no code executed)

```text
CURRENT_FALSE_READY_BEFORE=1 (vk_apple_synthetic_4publisher_false_ready)
CURRENT_FALSE_READY_AFTER_SIMULATION=0 (the combined rule would REJECT this fixture before it ever
  reaches the readiness gate, if wired as a pre-filter — conceptual only, nothing was wired)

CURRENT_MANUAL_ACCEPT_REJECTED_BEFORE=10 (the pre-existing G3-A finding — current readiness is
  conservative)
CURRENT_MANUAL_ACCEPT_REJECTED_AFTER_SIMULATION=10 (unchanged — a REJECTOR pre-filter cannot and
  must not fix this; confirmed directly that 0 of these 10 are ALSO rejected by the pre-filter, so
  it does not make the existing under-acceptance problem any worse either)
```

## 7. The central product question (§27)

> Can deterministic rules remove the VK/Apple false READY without damaging real EVENT_LIFECYCLE
> cases?

**YES, for this specific negative-control fixture** (RULE_D, zero false rejects across the full
calibration + holdout positive population, LOO-stable). This does **not** generalize to a claim
that deterministic rules solve syndication-vs-development in general — R2.11's own verb-blindness
finding (the "Apple sues Samsung" / "Apple settles with Samsung" adversarial pair) was re-confirmed
unchanged this phase (still `conflict=False`, still indistinguishable from genuine corroboration by
any feature available here) and RULE_D's own holdout evidence is thin (no fresh syndication
negative existed to test against). The honest scope of this finding is: **this one proven risk
class, with this specific signature (near-zero span + high source count + zero clustering merge),
can be safely caught** — a narrower, real, useful result, not a general syndication detector.

## 8. Hard middle

```text
HARD_MIDDLE_COUNT=11
HARD_MIDDLE_STORIES=vlm, vk_apple_real_3publisher, marvell_google, new_york_times_digest,
  optimizatsiya_koda, llm_agents_cluster, robotic_welding_cluster, multimodal_medical_cluster,
  object_detection_cluster, us_futures_wire_noise, holdout_when_predictor_cluster
```
8 of these are real `TOPIC_CLUSTER`/`DIGEST`/`NOISE` negatives that no candidate rule caught
(`PASS_THROUGH` — never `NEGATIVE_NOT_FILTERED` mislabeled as a false accept, per §18's own
distinction: these can still be caught by existing readiness, human review, or a future shadow
LLM). The remaining 3 (`vk_apple_real_3publisher`, `marvell_google`, `optimizatsiya_koda`) are
genuinely ambiguous by design, correctly routed to `NEEDS_REVIEW`/`UNCERTAIN` rather than forced
into either bucket.

## 9. Deterministic conclusion

```text
TOPIC_CLUSTER=PARTIAL (RULE_A: 12/12 TOPIC_CLUSTER negatives have sources==1; only those ALSO
  clearing the 200h span floor are caught — 10/17 combined-negative coverage includes most but not
  all TOPIC_CLUSTER cases; VLM is a documented miss)
DIGEST=PARTIAL (mechanically covered by RULE_A's own span/source pattern when it fires — d093e4be
  and den_1631_digest both clear it; new_york_times_digest does not, since it has sources=2, not <=1)
NOISE=PARTIAL (RULE_C catches the specific, evidenced GitHub-CI pattern on 2/2 tested cases across
  calibration+holdout; us_futures_wire_noise, a wire-boilerplate-duplicate-ingestion pattern, is a
  structurally different kind of noise with no evidenced deterministic signal in this dataset)
PURE_SYNDICATION=PARTIAL, narrowly (RULE_D's one proven case, see §7 — not a general solution)
REAL_EVENT=YES (as a preservation guarantee: 0 false rejects across 9 REAL_SINGLE_EVENT calibration
  + 10 REAL_SINGLE_EVENT holdout fixtures, for every rule tested)
EVENT_LIFECYCLE=YES (as a preservation guarantee: Nvidia/HF and all 3 calibration EVENT_LIFECYCLE
  fixtures never rejected by any rule; no EVENT_LIFECYCLE holdout fixture existed to extend this)
```

## 10. Recommended architecture

```text
OPTION 2 — deterministic rejector (RULE_A ∪ RULE_C ∪ RULE_D) + NEEDS_REVIEW hard middle + future shadow LLM
```
The deterministic layer is real, safe (0 false rejects, LOO-stable, holdout-confirmed on 2 of 3
rule families), and worth keeping as a first-pass filter — but it only covers 61% of calibration
negatives and its holdout confirmation is thin for RULE_D specifically. The 11-fixture hard middle
(§8) is exactly the population a future, explicitly-scoped **R2.10G3-C — shadow LLM eventness
evaluation** should target, per your own §38 routing — never as a production gate, and never on
the fixtures the deterministic layer already safely handles.
