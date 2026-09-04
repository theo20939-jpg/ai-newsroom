# R2.10G3-C — Shadow LLM Eventness Judge — Final Report

Shadow research only. Zero production code changed, zero DB writes, zero Telegram sends, zero
publication attempts, zero production readiness changes, zero Docker actions. Not merged into
`feature/phase19-editorial-depth-upgrade`. Not deployed.

## A. Base

```text
BASE_COMMIT=76c46aeb9e561cfc560000d4785a2ad2bd7b7354  (G3-B: G3_PARTIAL_REJECTOR_CALIBRATED_HARD_MIDDLE_REMAINS)
BRANCH=feature/r2-10-g3-shadow-llm-eventness
PRODUCTION_FILES_CHANGED=0
```
Verified: clean worktree created via `git worktree add ... -b feature/r2-10-g3-shadow-llm-eventness
76c46ae...`; `git status --short` was clean and `git rev-parse HEAD` was `76c46ae...` before any
edit. Every changed/added file lives under `scripts/`, `tests/`, `docs/`, or `prompts/`
(`tests/test_recap_r2_10_g3_llm_judge.py::test_no_production_files_changed_since_base_commit`
enforces this directly, diffing the base commit against the working tree).

## B. Evaluation set

```text
HARD_MIDDLE=11        (verbatim from G3-B §8's own HARD_MIDDLE_STORIES list, frozen before any LLM call)
POSITIVE_CONTROLS=6   (nvidia_hf_main, nvidia_mediatek, south_korea_policy, ai_challenge_10k,
                        holdout_claude_fable_mythos, holdout_pentagon_grok)
NEGATIVE_CONTROLS=4   (vla, vk_apple_synthetic_4publisher_false_ready, ciflow_ci_noise, utro_digest)
TOTAL=21
```
§6 also names VLM and Marvell/Google as mandatory negative/ambiguous controls — both already sit
inside the 11-fixture HARD_MIDDLE set (disclosed explicitly in code via `_AUXILIARY_CONTROL_ROLE`,
not double-called). No duplicate fixture_id exists in the target set (enforced by an assertion
inside `build_target_set()` and by `test_target_set_has_no_duplicate_fixtures_and_respects_hard_cap`).

Ground truth for this phase's own binary/ternary scoring is derived from `desired_eventness`, not
the literal manual_class table §7 describes — the same resolution G3-B's own `measure_rule()`
applied, for the identical reason: `vk_apple_synthetic_4publisher_false_ready`'s `manual_class` is
`REAL_SINGLE_EVENT` (a literal §7 POSITIVE_EVENT by class alone), yet the fixture's entire purpose
(§14/§28) is as the mandatory negative control a safe judge must REJECT. A literal
manual_class→ACCEPT mapping would have scored a correct REJECT on this exact fixture as the single
worst possible error — directly contradicting §14. `ground_truth_eventness()`'s own docstring
documents this explicitly. §6's literal manual_class grouping is still reported unmodified below
for spec compliance, never used for scoring.

## C. Prompt

```text
PROMPT_VERSION=1
PROMPT_HASH=69957ae40a937e2915883de734c9f964a464ccae78021446656a813d3662c8b0
MODEL_REQUESTED=gpt-5.6-luna (PREFERRED_MODEL - advisory only, see D below)
TEMPERATURE=not set (see D — the real provider model rejects an explicit temperature once
  reasoning_effort is set; discovered on this phase's own first live call attempt)
MAX_TOKENS=700
REASONING_EFFORT=low
```
One prompt-freeze sanity call (§22) against a fabricated, never-labelled fixture was made and
confirmed schema/parsing correctness (`SANITY_CHECK_PASSED=True`) BEFORE any real fixture was sent
— the prompt file was never edited after that point. Real fixture results are RUN 1 only; no RUN 2
was needed.

## D. Calls

```text
LLM_CALLS=22          (1 prompt-freeze sanity call + 21 real fixture evaluations)
PHYSICAL_CALLS=22     (max_same_candidate_retries=0, max_fallback_attempts=1 - every record shows
                        physical_provider_attempts=1, confirming no retry/fallback occurred on any call)
RETRIES=0
TOTAL_TOKENS=33,438   (input=31,746 output=1,692 - real fixtures only, sanity call excluded)
ESTIMATED_COST=$0.1047
```
**Real finding, corrected mid-phase**: `preferred_model="gpt-5.6-luna"` is *advisory only*
(`integrations/llm_gateway/routing/engine.py`'s own explicit "§4.1 rule 1" comment) — every one of
the 22 real calls actually dispatched to **`gpt-5.6-terra`** (the mid/"balanced" tier), not the
requested cheapest tier. `cost_report()` originally priced every call against `gpt-5.6-luna`'s
cheaper rate ($1/$6 per M tokens), understating real spend at $0.0419; fixed to price each record
by its own real `model_used` field (`gpt-5.6-terra`, $2.50/$15 per M tokens) — corrected figure
above, $0.1047, still trivially cheap and well inside any reasonable budget, but the ORIGINAL
under-reported number was wrong and is disclosed here rather than quietly overwritten.
`unpriced_record_ids=[]` — every record's real model priced successfully.

## E. Hard middle

```text
CORRECT=8/8
WRONG=0
UNCERTAIN=0
```
Every one of the 8 scorable HARD_MIDDLE fixtures (the 11 minus the 3 whose ground truth is itself
UNCERTAIN) was judged correctly — `vlm`, `new_york_times_digest`, `llm_agents_cluster`,
`robotic_welding_cluster`, `multimodal_medical_cluster`, `object_detection_cluster`,
`us_futures_wire_noise`, `holdout_when_predictor_cluster` were ALL correctly REJECTed, each with
HIGH confidence and content-grounded reasoning (e.g. `vlm`: "separate arXiv-style research items
... not developments of one identifiable underlying event"; `us_futures_wire_noise`: "all member
titles are effectively identical versions of a single market-update headline ... repeated
syndication"). This is the strongest single result of this phase — every deterministic-rule
blind-spot fixture that has a scorable ground truth was correctly resolved by the LLM.

## F. Positive controls

```text
FALSE_REJECTS=2   (nvidia_hf_main, holdout_pentagon_grok)
```
Both false rejects were HIGH confidence (`overconfident_wrong=true` for both — see K/error analysis).
`nvidia_hf_main` is the single most safety-critical fixture in the whole evaluation set (§13's own
"fragmentation safety" mandatory control) — its incorrect REJECT is the central negative finding of
this phase, discussed in full in J/K/M below.

## G. Negative controls

```text
FALSE_ACCEPTS=0
```
`vla`, `vk_apple_synthetic_4publisher_false_ready`, `ciflow_ci_noise`, `utro_digest` were all
correctly REJECTed, each HIGH confidence, with reason codes matching their own intended safety
category exactly (TOPIC_COLLECTION for vla, PURE_SYNDICATION for the VK synthetic fixture,
NON_EDITORIAL_NOISE for ciflow, DIGEST for utro_digest).

## H. Ambiguous

```text
OVERCLAIMS=3/3   (vk_apple_real_3publisher, marvell_google, optimizatsiya_koda)
CORRECT_UNCERTAIN=0/3
```
The model never once answered UNCERTAIN in this entire run, despite the prompt explicitly
permitting and encouraging it ("do not force a guess") and despite all three of these fixtures
being deliberately, manually left UNCLEAR/NEEDS_REVIEW by prior forensic phases specifically
because the evidence does not clearly resolve them. `marvell_google` (manually UNCLEAR, R2.11's own
explicit non-decision) was answered ACCEPT/HIGH-confidence/COHERENT_SINGLE_EVENT. This is a real,
disclosed calibration weakness, not scored as a "wrong" answer (UNCERTAIN ground truth is excluded
from binary scoring, per §18, so none of these count toward FALSE_ACCEPTS/FALSE_REJECTS above) but
a meaningful finding about the model's own willingness to self-report genuine uncertainty: on this
sample, it did not, at all.

## I. Overall non-ambiguous

```text
FALSE_ACCEPTS=0
FALSE_REJECTS=2
CORRECT_ACCEPTS=4
CORRECT_REJECTS=12
```
(scored_count=18 = 21 total − 3 UNCERTAIN-ground-truth fixtures; 0 skipped, 0 parse errors.)

## J. Hard fixture table

| Fixture | Deterministic (G3-B) | LLM opinion | Reason codes | Confidence | Correct? |
|---|---|---|---|---|---|
| VLA | REJECT | REJECT | TOPIC_COLLECTION, FRAGMENTED_BUT_REAL_EVENT | HIGH | ✅ |
| VLM | PASS_THROUGH (hard middle) | REJECT | TOPIC_COLLECTION, NON_EDITORIAL_NOISE | HIGH | ✅ |
| NVIDIA_HF | PASS_THROUGH (hard middle) | **REJECT** | PURE_SYNDICATION | HIGH | ❌ (should ACCEPT/FRAGMENTED_BUT_REAL_EVENT) |
| VK_APPLE_FALSE_READY | REJECT (already caught) | REJECT | PURE_SYNDICATION | HIGH | ✅ (redundant confirmation) |
| MARVELL | PASS_THROUGH (hard middle) | ACCEPT (ground truth UNCERTAIN) | COHERENT_SINGLE_EVENT | HIGH | overclaim, not scored |
| CI_NOISE | REJECT (already caught) | REJECT | NON_EDITORIAL_NOISE, TOPIC_COLLECTION, FRAGMENTED_BUT_REAL_EVENT | HIGH | ✅ |

## K. Error analysis

**1. `nvidia_hf_main` — REJECT_ON_MANUAL_POSITIVE, OVERCONFIDENT_WRONG.** This is the exact
mandatory fragmentation-safety control §13 named by name: "A genuine but fragmented event is still
an event... It must not be instructed that incomplete Story membership means REJECT." The prompt
(v1, rule 4) explicitly states this. The model rejected it anyway, reasoning "no distinct
substantive development in that acquisition lifecycle is evidenced" — i.e., it read the Story's own
known-fragmented evidence (G2's real, still-unfixed title-case entity-extraction defect splits this
one real acquisition across 4 separate Story rows) as *proof of pure syndication* rather than as
*incomplete coverage of a still-real event*. Failure cause (§27 taxonomy): **FRAGMENTATION_CONFUSED_WITH_NOISE**
— precisely the failure mode §13 was written to prevent, and it occurred anyway despite an explicit
rule against it.

**2. `holdout_pentagon_grok` — REJECT_ON_MANUAL_POSITIVE, OVERCONFIDENT_WRONG.** A real, single,
thinly-sourced announcement (one direct report + one Google-News-wrapped duplicate, identical
timestamp) manually labelled ACCEPT specifically because it is a genuine single event despite thin
sourcing. The model rejected it as PURE_SYNDICATION ("news.google.com looks like duplicating
ixbt.com, not independent development"). This is a defensible read of the *surface pattern*
(duplicate headline, same timestamp — the same shape as the mandatory VK/Apple negative control)
but wrong on the *substance* (one real event, not an attempt to inflate coverage of one fact into
apparent lifecycle depth). Failure cause: **SYNDICATION_CONFUSED_WITH_DEVELOPMENT** — the model
appears to apply "duplicate-headline shape ⇒ reject" too bluntly, without distinguishing "a single
real event reported thinly" (ACCEPT-worthy) from "many publishers repeating one fact to simulate
coverage depth" (REJECT-worthy, the VK/Apple control's own intended distinction). The same
underlying pattern-matching shortcut plausibly explains error 1 above as well.

**3. Three ambiguous overclaims (`vk_apple_real_3publisher`, `marvell_google`,
`optimizatsiya_koda`)** — not scored as wrong (excluded from binary scoring per §18) but a real
finding: the model answered decisively (ACCEPT/ACCEPT/REJECT, all HIGH confidence) on every single
one of the three fixtures deliberately left open by prior human forensic work. None of §27's listed
failure-cause categories cleanly fits "declined to self-report genuine uncertainty despite explicit
permission to" — reported here as its own distinct, disclosed finding rather than forced into an
ill-fitting bucket.

**4. Minor tooling false-positive (not a model error):** `vk_apple_real_3publisher`'s
`recommendation_language_detected=true` flag fired on the word "publisher" (a legitimate
evidence-domain word describing a news outlet) because `_RECOMMENDATION_LANGUAGE_RE`'s
`publish\w*` pattern matches it as a substring of "publisher". This is a known, disclosed limitation
of that diagnostic regex, not a model-output problem — it never affected scoring (a metadata flag
only, never gate logic).

## L. Cascade simulation

Conceptual only — no code change, no production implementation. `RULE_COMBINED`'s own REJECT
verdicts (from G3-B, unmodified) are never overridden by the LLM in this simulation (§29), verified
directly by `test_cascade_never_lets_llm_override_a_deterministic_reject`.

```text
DETERMINISTIC_NEGATIVES_FILTERED=4    (vla, vk_apple_synthetic_4publisher_false_ready, ciflow_ci_noise, utro_digest)
HARD_MIDDLE_SENT_TO_LLM=8
ADDITIONAL_NEGATIVES_CAUGHT_BY_LLM=8  (ALL 8 of the hard-middle remainder - 100% coverage on this sample)
LLM_FALSE_ACCEPTS=0
LLM_FALSE_REJECTS=2                   (both on POSITIVE_CONTROL fixtures - nvidia_hf_main, holdout_pentagon_grok)
```
On this specific 21-fixture sample, the combined deterministic+LLM cascade would have correctly
rejected all 12 manual negatives with zero false accepts — a materially stronger negative-coverage
result than the deterministic layer alone (which covered only 4/12 = 33% of this sample's
negatives, consistent with G3-B's own reported ~61-67% negative coverage on the larger calibration
set). But the LLM layer, on this same sample, incorrectly rejected 2 of 6 real positive controls
(33%) when evaluated — including the single most safety-critical fragmentation fixture. Since this
simulation's cascade design (§29) never lets the LLM promote a deterministic REJECT, those 2 false
rejects are attributable entirely to the LLM's own judgment on fixtures the deterministic layer
correctly left alone — meaning if the LLM's REJECT verdict were ever wired to auto-reject (rather
than flag for human review), it would introduce new false rejects the current system does not have.

## M. Recommendation

`LLM_SHADOW_ADDS_PARTIAL_VALUE`

The shadow LLM demonstrably adds real value the deterministic layer structurally cannot: it
correctly resolved 8/8 scorable hard-middle fixtures (100%) with zero false accepts anywhere in the
21-fixture set, including strong, content-grounded reasoning distinguishing topic collections,
digests, and pure syndication from real events. But it is measurably **not yet safe as an
autonomous reject signal**: it produced 2 HIGH-confidence false rejects among only 6 positive
controls (33%), one of them the single most explicitly-flagged safety fixture in this entire
project (§13's fragmentation-safety control), and it never once exercised the UNCERTAIN option on
3/3 genuinely ambiguous fixtures despite explicit permission to. This is not a case of the LLM being
unreliable in general (its negative-side performance was flawless on this sample) — it is a
specific, real, disclosed weakness at distinguishing "a real event with thin/fragmented coverage"
from "pure syndication of one fact," in exactly the direction that would hurt real events if ever
trusted to auto-reject.

## N. Tests

```text
SCOPED_TESTS=27 new (test_recap_r2_10_g3_llm_judge.py) + 19 G3-B (test_recap_r2_10_g3_eventness_calibration.py)
  + 20 G3-A (test_recap_r2_10_g3_eventness_harness.py) + 141 recap_event/event_recap
  (tests/test_recap_event.py + tests/test_event_recap.py) = 207 total, 0 failures.
  No r212-specific test file exists in this branch's own history to run (feature/r2-shadow-
  preparation's own scripts were ported without a companion test suite in G3-A; this phase's own
  Gateway safety wrapper is duplicated code from that script, independently covered by this
  phase's own H/I/J tests instead).
RUFF=clean (scripts/_recap_r2_10_g3_eventness_llm_judge.py, tests/test_recap_r2_10_g3_llm_judge.py)
MYPY=clean (scripts/_recap_r2_10_g3_eventness_llm_judge.py - "Success: no issues found in 1 source
  file"; mypy is scoped to script files only, matching G3-A/G3-B's own established convention of
  not type-checking test files)
```
Two real bugs were found and fixed via this test suite / the real run itself before the final
commit: (1) `compute_metrics()`'s `scored` filter did not exclude PARSE_ERROR rows, which would
have silently inflated `scored_count`; (2) `cost_report()` priced every call against the requested-
but-not-actually-dispatched `PREFERRED_MODEL`, understating real spend by ~2.5x once the real
`gpt-5.6-terra` routing was observed.

## O. Safety

```text
DB_WRITES=0
TELEGRAM_SENDS=0
PUBLICATION_ATTEMPTS=0
PRODUCTION_READINESS_CHANGES=0
DOCKER_ACTIONS=0
```
Verified structurally (AST-based import checks: no `telegram`/`bot.` import, no
`services.event_recap` import, no `.commit(`/`session.add(` anywhere in the module) and empirically
(`test_llm_path_cannot_write_db` — real Story/EditorialTask row counts unchanged before/after the
exact read-only DB pass `run_llm_judge()` uses). `existing_readiness_state` is read-only, carried
through from `evaluate_db_fixture()`/`evaluate_offline_fixture()` (G3-A, unmodified) — never
written.

## P. Commit

```text
COMMIT_CREATED=<see below>
COMMIT_SHA=<see below>
FILES_IN_COMMIT=<see below>
```
(Filled in after the commit is created — see the final report message.)
