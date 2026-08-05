# Phase 18.7 — Meme Intelligence Calibration Update: Calibration Results

Status: engineering complete, **algorithmic self-consistency replay only** — the human review of
Phase 18.6's packet still has not happened (every `human_*` field in
`scripts/phase18_6_calibration_dataset.json` remains blank), so no metric below is validated
against real human judgement. Every number in this report is either an algorithmic before/after
comparison on the existing v1 output, or explicitly marked as "not computable yet."

---

## 1. What this phase encodes, and from what evidence

The four findings in the Phase 18.7 brief map directly onto system-level pattern observations this
project already made and published *before* this phase started — not onto the (still-blank) human
review packet:

- **Finding 1** (M1 arXiv/academic false positives) ↔ `docs/phase18_6_meme_calibration_report.md`
  §6 / `docs/phase18_5_meme_shadow_validation_discovery.md`: 16 of 20 real Phase 18.6 `MEDIUM`
  samples were arXiv abstracts, 18 of 20 carried `contrast_connector` evidence.
- **Finding 3** (M3 "war"/technical-term false positives) ↔ `docs/phase18_5_final_report.md` §6:
  the real, previously-flagged "Gears of War" Nvidia-driver false positive and the "iPhone poll"
  `death_or_tragedy:killed` false positive.
- **Finding 2** (missing positive signals) and **Finding 4** (stay conservative) are new
  calibration additions this phase implements from the brief's own specification, not from a
  previously-observed false negative in this project's own data (no false-negative evidence exists
  yet — see §6).

This distinction matters and is stated plainly: this phase calibrates against **real, previously
published, evidence-backed false positives**, not against fabricated or hypothetical ones — but it
is still not the same thing as human-validated calibration, which remains pending.

## 2. Architecture — what changed and what did not

**Zero rewrites.** `services/meme_opportunity.py`, `services/meme_safety.py`, `services/
meme_quality.py`, `capabilities/executor.py`, and every migration file are byte-identical to the
prior checkpoint (`git diff --stat checkpoint/phase18-6-calibration-ready..HEAD` confirms this).

New, purely additive files:
- `schemas/meme_calibration_rules.py` — `MemeOpportunityAssessmentV2`, `SafetyContextExceptionResultV2`
- `services/meme_calibration_rules.py` — the v2 calibration layer itself
- `scripts/phase18_7_calibration_replay.py` — offline replay tool (this report's own data source)
- `tests/test_phase18_7_meme_calibration_rules.py` — 31 tests
- Two new `core.config.Settings` fields: `meme_opportunity_calibration_version` and
  `meme_safety_calibration_version`, both `Literal["v1", "v2"]`, both still `"v1"` (the brief's own
  "feature flags remain OFF" acceptance criterion). **Neither flag is consumed by any pipeline call
  site in this phase** — `CapabilityExecutor` still only ever calls the original v1 functions.
  Wiring v2 into the live shadow path is explicitly out of scope here (a `CapabilityExecutor`
  change is one of this project's own standing stop conditions) and is a candidate for a future
  phase, not this one.

**How v2 relates to v1, precisely:**
- M1: `assess_meme_opportunity_v2()` calls the unmodified `assess_meme_opportunity()` first, then
  applies a bounded score delta (`compute_calibration_delta()`) on top of its composite score.
  `SENSITIVE_BLOCK` and `INSUFFICIENT_SOURCE` pass through completely unchanged — calibration
  never overrides either short-circuit, mirroring v1's own "hard rejection wins regardless"
  precedence.
- M3/M1-shared sensitivity scan: `detect_sensitive_categories_v2()` calls the unmodified
  `detect_sensitive_categories()` first, then removes *individual phrase matches* a context
  exception covers — never a blanket per-category suppression. Every exception carries its own
  `override_markers` set; if any override marker is present, the exception is cancelled and the
  original v1 block is restored (Finding 4, enforced structurally, not just by convention).
- Policy versions: `MEME_OPPORTUNITY_CALIBRATION_POLICY_VERSION = "v2"`,
  `MEME_SAFETY_CALIBRATION_POLICY_VERSION = "v2"` (new, in `schemas/meme_calibration_rules.py`).
  `services.meme_opportunity.POLICY_VERSION`/`services.meme_safety.POLICY_VERSION` remain `"v1"`,
  unchanged — v1 stays fully accessible and callable exactly as before.

**M7 (Meme Quality Gate): no changes.** The brief's Objective lists M7 among the systems to
improve, but the brief's own "Human calibration findings to encode" section (Findings 1-4)
contains zero concrete findings about M7 — and Phase 18.6's human review packet doesn't cover
quality-gate signals at all (it only samples opportunity/safety decisions). Making an M7 change
with no grounding evidence would repeat exactly the mistake this project has consistently avoided
("do not invent results" — established in `docs/phase18_5_metrics_report.md` §7 and every report
since). M7 is therefore untouched this phase; see §7.

## 3. Old metrics (v1 baseline)

From the same, unmodified Phase 18.6 dataset (`scripts/phase18_6_calibration_dataset.json`, 50
items: 20 `MEDIUM`, 20 `LOW`, 10 `BLOCKED`), no change from Phase 18.6's own report:

| Group | Count | v1 label |
|---|---|---|
| A | 20 | `MEDIUM` |
| B | 20 | `LOW` |
| C | 10 | `BLOCKED` |

(Corpus-wide v1 rates, unchanged, from `docs/phase18_5_metrics_report.md`: opportunity rate 0.44%,
safety block rate 1.46% across the real 12,430-event corpus.)

## 4. New metrics (v2 replay, algorithmic — not human-validated)

`python scripts/phase18_7_calibration_replay.py`, run offline against the same 50-item dataset
(title + the dataset's own 280-character content excerpt — see §6 for why full article text was
not used):

| Group | Metric | Result |
|---|---|---|
| A (`MEDIUM`) | Items whose label changed | **12 / 20 (60%)** — all `MEDIUM → LOW`, all via `research_paper:*` penalty evidence |
| B (`LOW`) | Items whose label changed | **0 / 20** — zero false negatives recovered in this specific sample (§6) |
| B (`LOW`) | Items where the research-paper penalty *also* fired (label unchanged, already `LOW`) | 5 / 20 |
| C (`BLOCKED`) | Items genuinely unblocked (a real context exception fired) | **3 / 10** |
| C (`BLOCKED`) | Items correctly still blocked | 4 / 10 |
| C (`BLOCKED`) | Items **not verifiable from the stored excerpt** (v1's own original match isn't reproducible from the 280-char excerpt at all — a data limitation, not a calibration result) | 3 / 10 |

**"Safety false positive rate" (the brief's own requested metric), precisely defined**: of the 7
Group C items where the replay *could* reproduce v1's original match, 3/7 (43%) were genuine
keyword-only false positives fixed by the context-exception layer. This is **not** a corpus-wide
false-positive rate (the safety lexicon fires on 182 real events out of 12,430, of which 10 were
sampled here) and **not** validated against human judgement — it is an algorithmic measurement of
this specific 10-item sample only, reported precisely as such.

**Precision / recall / false-positive-rate against human ground truth: not computable.** Identical
to Phase 18.6's own honest finding — the human review packet is still blank. Nothing here
substitutes for that.

## 5. Changed cases

**Group A (`MEDIUM → LOW`, 12 items)** — every one carries `research_paper:arxiv_source` or
`research_paper:methodology` evidence; scores dropped by 22-26 points (e.g. `23ea0a26…`: 36 → 14,
`58246f78…`: 36 → 10). All 12 titles are arXiv-style abstracts ("Latent world models support
efficient model-predictive…", "Scientific images are the core elements of…", "Recent advances in
preference alignment for diffusion-…") — directly confirms Finding 1's premise on real data.

**Group C (`BLOCKED → UNBLOCKED`, 3 items, real context exceptions fired):**
- *"Sony анонсировала игру God of War Laufey…"* — `war:war` suppressed via the `god of war` /
  gaming-context safe marker.
- *"Gears of War: E-Day devs are embracing 'old-school' multiplayer…"* — `war:war` suppressed via
  the `gears of war` safe marker. (This is the exact same real event Phase 18.5 M4 §6 originally
  flagged — see §8, this is a direct regression-guard fix, not a new discovery.)
- A Warhammer 40K-related Russian-language gaming item — `war:war` suppressed via gaming-context
  markers (mangled console encoding in the raw title; verified correct via the underlying
  `event_id` and evidence fields, not the garbled display text).

**Group C (correctly still blocked, 4 items):**
- A flood/hydrometeorological item (`disaster:flood`, no exception exists for `disaster` — correct).
- *"Open weights vs. closed: An AI civil war's afoot…"* — `war:war` still fires. This is a **known,
  disclosed remaining false positive** ("civil war" as an industry-conflict metaphor, not a game
  title) that this phase's curated exception list does **not** cover — deliberately conservative
  (§9), not an oversight.
- A local-politics arrest item involving a minor (`minors_safety:child abuse` — correctly still
  blocked, no exception was ever defined for `minors_safety`, per Finding 4).
- An accidental-death risk item (`death_or_tragedy:death` — correctly still blocked; `death` was
  never given a context exception, only `died`/`killed` were, since "death" as a bare noun has no
  common benign technical usage the way "died"/"killed" do as verbs).

## 6. Known limitations

- **No human ground truth yet.** Every metric above is algorithmic self-consistency, not
  human-validated precision/recall. This is the same honest gap Phase 18.6 already disclosed and
  this phase does not close it.
- **Replay uses a 280-character excerpt, not full article text**, because the brief's own
  instruction was to "Use: phase18_6_calibration_dataset.json" (an offline, zero-database-access
  replay) rather than re-querying the database. This produced a real, caught methodological
  artifact: 3 of the 10 Group C items' original v1 trigger phrase isn't present within the stored
  excerpt at all, so the replay honestly reports these as `CANNOT_VERIFY_FROM_EXCERPT` rather than
  miscounting them as "fixed" (§4-5). A full-corpus recomputation against real full article text
  would need a separate, explicitly-authorized read-only DB run (mirroring Phase 18.5/18.6's own
  precedent) — not done in this phase.
- **Zero false negatives recovered in the Group B (`LOW`) sample.** This does not mean Finding 2's
  new positive signals are ineffective — only that this specific, small, random 20-item sample
  happened not to contain gaming-controversy/company-drama/brand-conflict/human-emotion language
  strong enough to cross the `REVIEW` threshold. Evaluating recall properly needs either a larger
  sample or a full-corpus replay, neither of which this phase performed.
- **The curated M3 exception list is intentionally narrow.** It covers exactly the cases named in
  the brief (`god of war`/`gears of war`/`total war` + a general gaming-context marker set for
  "war"; `died`/`killed` + technical-process context; `shooting` + photography/trajectory context).
  It does **not** catch every possible metaphorical false positive (§5's "AI civil war" example) -
  expanding the curated list further without more real evidence would risk the same
  "invent-a-fix-for-an-untested-case" mistake this report is trying to avoid.
- **Two of the brief's Finding 3 examples were verified as already non-issues in v1**, not fixed by
  this phase because there was nothing to fix: `services/meme_opportunity.py`'s lexicon has no
  bare `"crash"` trigger anywhere (`disaster`/`death_or_tragedy` categories were checked directly),
  and `crime_with_victim`'s only "shot"-rooted phrases are the two-word `"shot by"`/`"shot dead"` -
  a bare `"shot"` (as in "we shot this image") was never a trigger to begin with. Verified by
  direct inspection of the lexicon source, not assumed.

## 7. M7 (Meme Quality Gate) — explicitly out of scope

No change was made to `services/meme_quality.py`. The brief names M7 in its Objective but supplies
no calibration finding for it, and Phase 18.6's human review packet does not sample quality-gate
decisions at all. Any M7 change made here would be invented, not calibrated — inconsistent with
this project's stated evidence discipline. If quality-gate calibration is wanted, it needs its own
finding-gathering step (e.g. a Phase 18.6-style human review packet scoped to M7's own
`READY_FOR_EDITOR`/`REVIEW`/`REGENERATE_*`/`REJECT` decisions) before any code change is justified.

## 8. Tests

`tests/test_phase18_7_meme_calibration_rules.py` — **31 tests**, all passing:
- Threshold drift guard (1): confirms the calibration module's imported v1 thresholds are 55/35.
- M1 Finding 1 (4): arXiv paper score reduction, non-arXiv research-style penalty, penalty cap at
  -30, non-research text gets zero penalty.
- M1 Finding 2 (6): company drama, gaming controversy, brand+conflict, brand-alone-no-bonus gate,
  human emotion, total positive delta cap at +25.
- M1 hard-short-circuit preservation (2): `SENSITIVE_BLOCK`/`INSUFFICIENT_SOURCE` pass through v2
  completely unchanged.
- M3 Finding 3 allowed cases (4, parametrized to cover God of War / Gears of War / Total War): game
  franchise titles not blocked for "war"; shooting-trajectory, process-died, app-killed not blocked.
- M3 Finding 4 blocked cases (7): real shooting incident, child abuse, real disaster, real death
  event, override markers cancelling both the "war" and "died" exceptions, and partial suppression
  (category still fires when a second, non-exempted phrase also matches).
- Real regression guard (1): the exact, previously-flagged Phase 18.5 "Gears of War" Nvidia-driver
  false positive, verified fixed.
- Schema validation (2): both new V2 schemas are frozen and `extra="forbid"`.
- Import-boundary / no-rewrite checks (2): no forbidden imports (LLM/Telegram/image/DB), and the
  calibration module never redefines v1's own lexicon/weight constants.

**Existing Phase 18 tests**: `pytest -k "phase18 or meme"` — see §9 for the full comparison; no
existing test file was modified, so no existing test's behavior changed.

## 9. Regression comparison

`python -m pytest -q` (full suite, real `ai_newsroom`-backed database): **2,435 tests collected,
2,404 passed, 31 failed** (2,428.84s / 40m28s).

**Comparison against Phase 18.6's own baseline** (`docs/phase18_6_meme_calibration_report.md`
Appendix: 2,404 collected, 2,375 passed, 29 failed) and Phase 18.5's original baseline (31 failed):
this run's 31 failures are the **exact same 31-item set** Phase 18.5 first identified — the 10
`meme_candidates`-table-missing failures, the 19 pre-existing FK-violation/data-state failures, and
this time **both** instances of the already-documented timing-flaky
`test_cycle_level_infrastructure_failure_logs_and_waits_for_next_interval` failed (Phase 18.6's own
run happened to have both pass instead) - consistent with genuine non-determinism, not a
regression. `git diff --stat checkpoint/phase18-6-calibration-ready..HEAD` confirms zero
modification to any of these 12 failing test files or anything they import beyond what Phase 18.7
itself newly added. **Zero new failures.**

All **31 new Phase 18.7 tests pass** and are among the 2,404 passed - zero among the 31 failed.
Targeted `pytest -k "phase18 or meme"` run separately: 282 passed, 10 failed (the same 10
`meme_candidates` failures only - confirms the FK-violation/flaky-test failures are outside this
narrower slice). `ruff check` / `mypy --ignore-missing-imports` on all 5 new non-test files plus
the modified `core/config.py`: all clean.

## 10. Next recommendation

1. This phase's output is **calibration tooling and an algorithmic replay**, not a validated fix.
   Do not set `meme_opportunity_calibration_version`/`meme_safety_calibration_version` to `"v2"` in
   production, and do not wire either into `CapabilityExecutor`, until:
   - Phase 18.6's human review packet is actually reviewed, and
   - the 3 `CANNOT_VERIFY_FROM_EXCERPT` Group C cases are re-checked against full article text.
2. If those two steps confirm the calibration direction is sound, wiring v2 into the existing
   shadow hooks (still `"off"` by default, matching every prior milestone's own activation
   discipline) would be the natural next engineering step — but that is a `CapabilityExecutor`
   change and requires its own separate authorization, per this project's standing stop conditions.
3. M7 calibration needs its own evidence-gathering step first (§7) before any code change there is
   justified.

**Phase 19 is explicitly not started by this report.** Engineering work stops here pending separate
confirmation, per instruction.
