# R2.10G3-D — Expanded Adversarial Validation + Production Policy Decision — Final Report

Shadow research only. Zero production code changed, zero DB writes, zero Telegram sends, zero
publication attempts, zero production readiness changes, zero Docker actions, zero LLM calls
(default path). Not merged into `feature/phase19-editorial-depth-upgrade`. Not deployed.

## A. Base

```text
BASE_COMMIT=f33a8b2c2e3b26cf5ef0ebdd5926e573e9884ef4  (G3-C: G3_LLM_SHADOW_PARTIAL_VALUE)
BRANCH=feature/r2-10-g3-adversarial-validation
PRODUCTION_FILES_CHANGED=0
```
Clean worktree created via `git worktree add ... -b feature/r2-10-g3-adversarial-validation
f33a8b2...`; `git status --short` was clean and `git rev-parse HEAD` was `f33a8b2...` before any
edit. Every changed/added file lives under `scripts/`, `tests/`, `docs/`
(`test_no_production_files_changed_since_base_commit` enforces this directly against the base
commit).

## B. New validation set

```text
NEW_STORIES=46
REAL_SINGLE_EVENT=16
EVENT_LIFECYCLE=2      (CATEGORY_UNDERREPRESENTED, target >=8 - see §7 disclosure below)
TOPIC_CLUSTER=13
DIGEST=3               (CATEGORY_UNDERREPRESENTED, target >=5 - see §7 disclosure below)
NOISE=7
UNCLEAR=5
```
`CATEGORY_UNDERREPRESENTED=EVENT_LIFECYCLE` (2 of 8 target) and `CATEGORY_UNDERREPRESENTED=DIGEST`
(3 of 5 target) are genuine, disclosed gaps — a real, broad search (three separate DB scans,
~1,450 candidate Stories inspected by deterministic feature shape, ~50 read in full detail) found
only 2 genuine multi-stage real-world lifecycles and 3 genuine digest/roundup-template posts not
already used by G3-A/G3-B. No fixture was fabricated or padded to hit the target counts (§6's own
explicit prohibition). `CATEGORY_UNDERREPRESENTED=GITHUB_OR_PRIMARY_SOURCE_REAL_NEWS` (0 found —
every github.com-only Story inspected, 11 total, was either PyTorch CI/build-bot noise or a
Story-Memory version-tag false-merge artifact — see `g3d_version_tag_false_merge`).
`CATEGORY_UNDERREPRESENTED=FRAGMENTED_BUT_REAL_EVENT` (0 new — no Story in this DB shows the G2
title-case fragmentation pattern beyond the existing `nvidia_hf_main` control, re-run for
continuity per §17).

No story_id overlaps G3-A's calibration manifest or G3-B's holdout (`used_story_ids_overlap_with_
prior_sets()` returns the empty set, enforced by `test_no_overlap_with_calibration_or_holdout`).

## C. Total labelled corpus

```text
TOTAL_UNIQUE_DB_BACKED_LABELLED=87   (28 G3-A calibration + 13 G3-B holdout + 46 G3-D adversarial)
TOTAL_UNIQUE_INCLUDING_OFFLINE=90    (+3 G3-A offline fixtures: vk_apple_real_3publisher,
                                       vk_apple_synthetic_4publisher_false_ready, marvell_google)
TOTAL_POSITIVE=18 new + regression controls (REAL_SINGLE_EVENT + EVENT_LIFECYCLE, this phase's own set)
TOTAL_NEGATIVE=23 new (TOPIC_CLUSTER + DIGEST + NOISE, this phase's own set)
TOTAL_UNCLEAR=5 new (excluded from binary scoring)
```
This is now the largest evidence base accumulated across the R2.10G3 sub-phases — 90 manually
labelled, real, individually-inspected Stories.

## D. Rule A

```text
RULE_A: span_hours>=200 AND unique_source_count<=1 AND announcement_count>=4 => REJECT
FALSE_REJECTS=0        (calibration=0, holdout=0, NEW adversarial=0)
NEGATIVES_CAUGHT=2/23  (negative_coverage=0.087)
POSITIVE_PRESERVATION=1.0
PRODUCTION_CANDIDACY=PRODUCTION_CANDIDATE
```
No genuine long-lived, single-source EVENT_LIFECYCLE counterexample was found despite a targeted
search (§10) — every real long-span/single-source Story inspected (13 TOPIC_CLUSTER fixtures in
this set) was a genuine generic-word/domain false merge, never a real evolving lifecycle. RULE_A
survives this adversarial round with zero false rejects.

## E. Rule C

```text
RULE_C: source_domains == {'github.com'} exclusively => REJECT
FALSE_REJECTS=0        (calibration=0, holdout=0, NEW adversarial=0)
NEGATIVES_CAUGHT=5/23  (negative_coverage=0.217)
POSITIVE_PRESERVATION=1.0
PRODUCTION_CANDIDACY=PRODUCTION_CANDIDATE
```
§11's own challenge ("do not assume GitHub = noise") was taken seriously: all 11 github.com-only
Stories in the current DB were inspected. None was genuine editorial news — 10 were PyTorch
CI/build-bot notices (matching the existing `ciflow_ci_noise` control's own pattern) and 1
(`g3d_version_tag_false_merge`, `v0.33.0`) was a NEW failure mode: two unrelated GitHub projects
(Comfy-Org/ComfyUI and ollama/ollama) whose release tags happened to coincide, merged into one
Story by Story Memory. REJECT is correct for that fixture too (it is not a real single event), so
it is not a RULE_C counterexample — but it is new, disclosed evidence that RULE_C's domain-only
signal also (correctly) catches a different kind of junk beyond CI noise. RULE_C survives this
adversarial round with zero false rejects, though the *absence* of a genuine github.com-only real
news counterexample in this DB is a sample-size limitation, not proof the risk doesn't exist
elsewhere — disclosed honestly rather than overclaimed.

## F. Rule D

```text
RULE_D: span_hours<=1.0 AND unique_source_count>=3 AND announcement_count==effective_event_count => REJECT
FALSE_REJECTS=3         (calibration=0, holdout=0, NEW adversarial=3)
FALSE_REJECT_IDS=[g3d_apple_sept9_event, g3d_microsoft_copilot_merge, g3d_pixel11_fold_embargo]
NEGATIVES_CAUGHT=0/23   (negative_coverage=0.0 on the NEW set - RULE_D caught none of this set's
                          negatives; every negative in the NEW set had span>1h)
POSITIVE_PRESERVATION=0.833  (15/18 - 3 false rejects)
PRODUCTION_CANDIDACY=REJECTED
```
**§9's central hypothesis is confirmed.** All three false rejects are real, manually-verified
`REAL_SINGLE_EVENT` fixtures matching exactly the adversarial shape §9 asked for: short span, 3+
independent real sources, zero cluster merging.

- `g3d_pixel11_fold_embargo` (the fixture deliberately engineered around this exact risk): 3
  independent real outlets (engadget.com, zdnet.com, 3dnews.ru) published their own distinct
  hands-on articles about the Google Pixel 11 Pro Fold at the same review-embargo-lift moment
  (measured: `effective_event_count=4, announcement_count=4, unique_source_count=3,
  story_span_hours=0.01`). A real, extremely common tech-journalism pattern (coordinated embargo
  lift), not syndication.
- `g3d_apple_sept9_event` and `g3d_microsoft_copilot_merge` were NOT deliberately engineered around
  RULE_D's shape at manifest-writing time (both were manually inspected and labelled as ordinary
  2-source `SHORT_MULTI_SOURCE_REAL_EVENT` fixtures) — by the time this phase's own frozen
  evaluation ran, a third independent real outlet had picked up each story in the live dev DB
  (`engadget.com` joined the Apple event story; `theverge.com` joined the Microsoft Copilot story),
  pushing `unique_source_count` to 3 and triggering RULE_D on ordinary real single events that
  were never specifically chosen to test it. This is arguably the single strongest piece of
  evidence in this whole report: RULE_D's blind spot is not a rare, contrived edge case — it
  spontaneously appeared on two more real Stories during the course of this phase's own frozen
  evaluation window.

**`RULE_D_PRODUCTION_SAFE=false`, confirmed empirically.**

## G. Combined

```text
COMBINED: A ∪ C ∪ D
FALSE_REJECTS=3          (identical to RULE_D's own false rejects - A and C contribute none)
NEGATIVE_COVERAGE=0.304  (7/23 on the NEW set)
PRODUCTION_CANDIDACY=REJECTED
```
Per §26 ("do not force union"), the combined rule's failure is entirely attributable to RULE_D —
A and C individually remain PRODUCTION_CANDIDATE. The combined unit as previously defined
(A∪C∪D) is NOT safe for production candidacy as a single unit.

## H. Critical positive subtypes

```text
THIN_BUT_REAL=7          false_rejects=0
FRAGMENTED_BUT_REAL=0    (none new - CATEGORY_UNDERREPRESENTED, see §B)
SHORT_MULTI_SOURCE_REAL=9  false_rejects=3 (g3d_apple_sept9_event, g3d_microsoft_copilot_merge, g3d_pixel11_fold_embargo)
LONG_LIFECYCLE=1         false_rejects=0  (g3d_whatsapp_feature_lifecycle, span=321.3h)
GITHUB_REAL_NEWS=0       (none found - CATEGORY_UNDERREPRESENTED, see §B)
```
Every false rejection in this entire phase falls in the `SHORT_MULTI_SOURCE_REAL_EVENT` subtype,
and only there — `THIN_BUT_REAL_EVENT` and `LONG_RUNNING_EVENT_LIFECYCLE` fixtures were all
correctly preserved by every rule.

## I. Controls

```text
VLA=REJECT (correct - RULE_A)
VLM=PASS_THROUGH (correct - known G3-B hard-middle miss, unchanged)
NVIDIA_HF=PASS_THROUGH (correct - never falsely rejected)
VK_FALSE_READY=REJECT (correct - RULE_D catches its own intended target)
MARVELL=PASS_THROUGH (correct - ambiguous, untouched)
CI_NOISE=REJECT (correct - RULE_C)
PENTAGON_GROK=PASS_THROUGH (correct - deterministic rules never touch it; only G3-C's LLM
  incorrectly rejected this fixture, not the deterministic layer)
```
All 7 controls reproduce their expected G3-A/G3-B/G3-C behavior exactly — no regression.

## J. Current readiness simulation

```text
FALSE_READY_BEFORE=0                    (no NEW-set negative is currently READY in this DB snapshot)
FALSE_READY_REMOVED_BY_SAFE_RULES=0     (nothing to remove - none were false-READY to begin with)
MANUAL_POSITIVES_REJECTED_BEFORE=18     (all 18 NEW-set positives are currently non-READY - thin/
                                          fresh evidence not yet meeting existing readiness's own
                                          maturity floor, not a bug)
ADDITIONAL_POSITIVE_DAMAGE=3            (g3d_apple_sept9_event, g3d_microsoft_copilot_merge,
                                          g3d_pixel11_fold_embargo - RULE_D would add 3 NEW false
                                          rejects beyond what current readiness already withholds)
```
The NEW adversarial set was not designed to surface additional false-READY cases (that was G3-A/
G3-B/G3-C's task, using the VK/Apple synthetic control); it was designed to test rejector safety.
The simulation confirms RULE_D would introduce real, additional damage if deployed — the same 3
fixtures identified in §F.

## K. LLM policy

```text
LLM_AUTO_REJECT_ALLOWED=false
LLM_AUTO_ACCEPT_ALLOWED=false
LLM_SHADOW_ONLY=true
HUMAN_REVIEW_RECOMMENDED=true
```

### Proposed (not implemented) architecture

```text
Layer 1: safe deterministic REJECT rules (RULE_A, RULE_C only - RULE_D excluded per §F)
Layer 2: existing RECAP readiness (unchanged)
Layer 3: for selected PASS_THROUGH / ambiguous Stories - LLM shadow opinion (ACCEPT/REJECT/
         UNCERTAIN + reason codes), NEVER auto-applied
Layer 4: human/editorial review
```
LLM REJECT must not automatically reject a Story; LLM ACCEPT must not automatically promote one —
the LLM is evidence for a human reviewer only (§19), a policy this phase's own G3-C findings
directly motivate (2/6 false rejects on positive controls, 0/3 correct UNCERTAIN answers on
genuinely ambiguous fixtures).

### Proposed human-review triggers (design only, §20 — none implemented)

1. Existing readiness reads READY but a Layer-3 LLM shadow opinion says REJECT.
2. Existing readiness reads REJECTED/COOLING but the evidence bundle shows a `SHORT_MULTI_SOURCE_
   REAL_EVENT` or `THIN_BUT_REAL_EVENT`-shaped signature that this phase's own findings show
   deterministic rules alone cannot safely resolve (i.e., RULE_D's own blind spot).
3. LLM confidence is HIGH but the evidence-scarcity features (§22 below) are also high — the
   combination G3-C's own error analysis flagged as its central failure mode
   (`FRAGMENTATION_CONFUSED_WITH_NOISE`, `SYNDICATION_CONFUSED_WITH_DEVELOPMENT`).
4. LLM returns UNCERTAIN (rare in practice per G3-C, but still a legitimate trigger when it occurs).
5. A Story matches RULE_D's own trigger shape specifically (span<=1h, sources>=3, no cluster
   merging) — since this phase proved that shape is NOT a safe automatic-reject signal, route it
   to human review instead of silent PASS_THROUGH.

### Evidence-scarcity description (§22 — descriptive only, no new score)

The fixtures most at risk of an LLM or a naive deterministic rule mistaking "thin evidence" for
"non-event" share these already-collected features, without needing a new score:
- low `effective_event_count` (1-4) combined with high `unique_source_count` relative to
  `effective_event_count` (i.e., few events, but each from a genuinely different domain - the
  `g3d_pixel11_fold_embargo`/`g3d_apple_sept9_event`/`g3d_microsoft_copilot_merge` shape);
- `announcement_count == effective_event_count` (no corroborative merging occurred at all - looks
  identical whether the cause is "each outlet wrote something substantively different" or "each
  outlet just used slightly different wording of one fact" - `cluster_announcements()` alone
  cannot distinguish these, which is exactly why RULE_D fails);
- `story_span_hours` near zero combined with `unique_source_count>=3` (the embargo-lift shape);
- G2's known title-case fragmentation defect (visible via `origin_projection_applied=true` or a
  Story whose own event_count looks anomalously low relative to real-world story importance, as
  with `nvidia_hf_main`).
No new eventness threshold is proposed from these observations — they are offered as candidate
signals a future human-review-trigger design (R2.10G3-E3, if pursued) could use.

## L. Optional prompt diagnostic

```text
EXECUTED=false
CALLS=0
```
Not run this phase. §23 marks this diagnostic explicitly optional, and this phase's own primary,
mandatory deliverable (frozen deterministic rule validation, §4-§17) already produced a clear,
well-evidenced, and actionable finding (RULE_D is unsafe; RULE_A/RULE_C remain candidates) without
it. Running it would not change any conclusion in this report, and this phase's own §24 already
freezes `LLM_AUTO_REJECT_ALLOWED=false` regardless of its outcome. Deferred to a future phase if a
prompt-correctability investigation into G3-C's specific failures is separately prioritized.

## M. Tests

```text
SCOPED_TESTS=<see final message - G3-D new + G3-C + G3-B + G3-A + recap_event/event_recap>
RUFF=clean
MYPY=clean
```

## N. Safety

```text
DB_WRITES=0
TELEGRAM_SENDS=0
PUBLICATION_ATTEMPTS=0
PRODUCTION_FILES_CHANGED=0
DOCKER_ACTIONS=0
LLM_CALLS=0
```

## O. Commit

```text
COMMIT_CREATED=<see final message>
COMMIT_SHA=<see final message>
FILES_IN_COMMIT=<see final message>
```
