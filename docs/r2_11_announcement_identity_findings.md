# R2.11 — Announcement Identity / Readiness Safety Findings

**Result: DESIGN ONLY. No production code was implemented or changed this checkpoint.**
Isolated worktree `../ai-newsroom-r211`, branch `feature/r2-11-announcement-identity`, based on
approved commit `183faf915eee95cf5b66e02f9f285fbcc0b604d0`. No production access, no paid LLM
calls, no pushes.

## Phase 1 — Contract reconstruction

Trace: `build_event_recap_candidate()` (services/event_recap.py, R2-owned) calls
`cluster_announcements()` (**services/recap_event.py, FROZEN R1**) → `len(clusters)` becomes
`announcement_count`, fed unmodified into `evaluate_recap_readiness()` (also frozen R1).
`AnnouncementCluster`, `_best_cluster_match_score()`, `_announcement_similarity()`,
`_has_distinctive_shared_evidence()`, `_has_temporally_corroborated_distinctive_evidence()`,
`_has_conflicting_distinctive_facts()` are ALL owned by `services/recap_event.py` — every one is
frozen. Nothing in this checkpoint modifies that file.

**What does "announcement" currently mean?** Reading the implementation and its own extensive
inline forensic history (R1.4/R1.4.1/R1.4.2 corrections, each citing real measured production
pairs) gives a precise, non-obvious answer:

**Answer: (C) — a heuristic cluster, deliberately biased toward the "one publication" end of the
spectrum whenever evidence is ambiguous.** Two events join the same cluster only when: (1) their
titles are near-exact (allowed to compare against any existing cluster member — a near-equivalence
relation), or (2) compared **only against the cluster's own stable reference** (never any member —
R1.4.1/R1.4.2 both found and fixed real transitive-chaining bugs from any-member comparison),
ordinary weighted title/entity similarity clears 0.75, **or** a lexical-floor path requiring
`symmetric_token_overlap >= 0.60` plus shared entity/number evidence and no conflicting fact,
**or** a temporal path requiring a genuinely new content-overlap floor (`>= 0.20`, excluding the
shared entity itself) **and** a 5-minute window **and** no conflicting fact. `_has_conflicting_
distinctive_facts()` — a differing number on either side, or an asymmetric entity on either side —
**vetoes every one of the non-identity paths**, unconditionally. The module's own repeated stated
philosophy: *"quality > recall," "prefer conservative split over unsafe general merge."*

This is **CURRENT IMPLEMENTED CONTRACT**, not **DESIRED EVENT_RECAP PRODUCT SEMANTICS**. R1 never
claims to answer "is this a distinct underlying development" — it answers "is this evidence strong
enough to say two reports are near-certainly about the identical specific fact," and defaults to
"no" (separate clusters) whenever that bar isn't cleared. `announcement_count` therefore currently
measures something closer to *report_count, conservatively deduplicated only in the clearest
cases* — not *development_count*. R2's readiness gate feeds this value into
`recap_min_announcement_count` as if it already meant "count of distinct story developments" — an
**R2-level type conflation**, not an R1 defect.

## Phase 2 — Real fixture reproduction (offline, no production query)

**Fixture A — VK/Apple** (exact production titles): `cluster_announcements()` on the 3 real
headlines → **`announcement_count = 3`**, matching the production observation exactly. Story
Integrity independently PASSES (2/2 or 3/3 coherent, ratio 1.00) — correctly, since Integrity's
job is coherence, not distinctness.

**Fixture B — Marvell** (exact production titles): also **`announcement_count = 3`**. Unlike VK,
every pairwise combination here registers `_has_conflicting_distinctive_facts() == True` (real
distinguishing content — see Phase 10).

Both reproduced exactly; see `tests/test_recap_r2_11_announcement_identity_forensic.py::
test_case1_*`/`test_case2_*`.

## Phase 3 — False-positive readiness proof: **YES, CONFIRMED**

A synthetic 4-publisher fixture (VK-shaped: same single real event, 4 distinct outlets, no shared
distinctive number, no near-exact title match, gaps wide enough to clear R1's own 5-minute
temporal window) produces `cluster_announcements() → 4 clusters`, Story Integrity PASS, 4 unique
sources, and — with `research_complete=True` supplied **only in this isolated test** (R2 never
sets this True in current production) and cooling elapsed —
**`evaluate_recap_readiness()` returns `ready=True, state=READY`.**

**Four reports of one real event, zero actual development, can reach natural READY.** Confirmed by
direct execution (`tests/test_recap_r2_11_announcement_identity_forensic.py::
test_case3_four_publisher_same_event_can_reach_natural_ready`), not inferred.

A control fixture — a genuine 4-stage development (announce → pricing → regulatory block →
company response, hours apart, each stage introducing a new distinctive fact) — correctly stays at
4 separate clusters via the SAME mechanism, proving R1 does not systematically under-split real
development; the risk is specific to near-simultaneous, conflict-free corroboration.

## Phase 4 — Duplicate report vs. development taxonomy

| Case | Shape | Current R1 behavior | Product-intent interpretation |
|---|---|---|---|
| 1 — corroboration | 4 outlets, same fact, minutes apart | Currently split unless near-exact text or the 5-min/0.20-floor temporal path fires | ONE announcement, multiple supporting sources |
| 2 — real development | Announce → price → block → response, hours apart | Correctly split (proven, Phase 3 control) | Multiple distinct announcements — correct today |
| 3 — same event, richer detail (Marvell) | A: deal announced; B: same deal, $12.2B; C: same deal, 58M shares | Currently split — EVERY pair registers a numeric conflict | **Deliberately left undecided** — see Phase 10; R1's own conflict veto already treats a new distinctive number as evidence of a real sub-announcement, and this checkpoint found no safe way to override that without also risking Case-2-shaped false merges |

## Phase 5 — Ownership / frozen boundary: **(A)**

**Current R1 announcement identity is correct by its own contract.** R1 never promised to solve
"corroboration vs. development" — it solves "conservative report-level deduplication," and does so
well at both extremes (Phase 2/4 control cases). **EVENT_RECAP (R2) would need its own local
interpretation layer before feeding `announcement_count` to readiness** if this risk is ever to be
closed — but see Phase 6/7 for why that layer was not built tonight.

## Phase 6/7 — R2-local design, evaluated and **REJECTED (not implemented)**

Candidate design (approach 3 from the checkpoint's own menu): reuse the existing, frozen
`_has_conflicting_distinctive_facts()` signal, applied cluster-to-cluster (via each cluster's own
stable reference, mirroring R1's own transitive-chaining-avoidance discipline) to collapse clusters
into an "effective announcement" count for readiness purposes only, leaving `announcement_count`,
stored clusters, source_refs, and all facts completely untouched.

**Tested directly, three independent findings blocked it:**

1. **Verb/action blindness.** `_has_conflicting_distinctive_facts()` only inspects numbers and
   entities. A constructed, entirely realistic adversarial pair — `"Apple sues Samsung over patent
   infringement"` vs. `"Apple settles patent dispute with Samsung amicably"` — has **identical**
   entities `{apple, samsung}`, zero numbers on either side, and registers `conflict=False`,
   **indistinguishable from genuine VK-style corroboration** by this signal. Entity overlap is
   *maximal* here, which is exactly why it's dangerous rather than reassuring — no existing
   deterministic signal in this codebase (entity Jaccard, numeric-token equality, title lexical
   overlap) captures the verb/action that actually distinguishes "same fact restated" from "a
   different development involving the same parties." Confirmed by direct execution
   (`test_case5_same_entities_different_action_is_a_precision_risk`).
2. **The reusable signal is itself corrupted.** `_has_conflicting_distinctive_facts()` calls the
   **frozen** `_extract_numeric_tokens()` — which still has the exact decimal-comma bug fixed
   RECAP-locally in `services/event_recap.py` last night (R2.10 Night 2), never in the frozen
   file. Confirmed: Marvell's own EN/RU pair ("12.2" vs the still-broken "122") registers as a
   *numeric conflict* purely from this artifact — meaning the one existing signal available for a
   collapse rule is not even reliable on its own terms for cross-language identical figures
   (`test_case2b_frozen_numeric_conflict_check_still_uses_the_unfixed_decimal_comma_extractor`).
3. **No real corpus to calibrate a time-window mitigation against.** A bounded time window (e.g.
   reusing the existing `recap_cooling_window_minutes=90` constant) would reduce but not eliminate
   risk #1 — a genuine two-stage development *can* occur within any bounded window in principle,
   and this checkpoint has zero real production pairs of "same-entity, opposite-action, within N
   minutes" to establish that a chosen window is actually safe.

Per the checkpoint's own explicit Phase 7 gate ("deterministic rule has strong precision... if any
condition is not met: DO NOT IMPLEMENT"), **condition not met — design documented, not built.**
`services/recap_event.py` was never touched.

## Phase 8 — Regression matrix

10 characterization tests added, `tests/test_recap_r2_11_announcement_identity_forensic.py`, all
passing, all pinning **current** (unmodified) behavior:

| # | Case | Result |
|---|---|---|
| 1 | VK 3-publisher, same event | `announcement_count=3` (reproduces production) |
| 2 | Marvell 3-report | `announcement_count=3`, every pair conflicts |
| 2b | Marvell EN/RU conflict artifact | frozen extractor still sees "12.2" ≠ "122" |
| 3 | 4-publisher false-positive | **natural READY confirmed** |
| 4 | Genuine 4-stage development | stays 4 clusters (control) |
| 5 | Same entities, different action | conflict=False — the precision limit |
| 6 | Same action, different value | conflict=True (correct control) |
| 7 | Identical text, different publisher | already merges to 1 (control) |
| 8 | Later source, new number, no conflict shape | conflict=False (documented boundary, not a claim) |
| 9 | Contradicting numeric values | conflict=True (correct control) |
| 10 | Origin-projected + duplicate reports | origin mechanics unaffected, still 3 clusters |

No implementation exists, so evidence-preservation assertions (source_refs, evidence_reference_
count, MULTI_SOURCE_CONFIRMED, anchor, publishable) were not separately re-tested here — nothing
about the evidence pipeline changed this checkpoint; the existing R2.10 test suite already covers
all of those invariants against unmodified code.

## Phase 9 — Scanner consequences

No ranking architecture change (nothing to change — no corrected R2 output exists).
`scripts/_recap_r2_10_readiness_candidate_scanner.py::scan_story_readiness()` gained a documentation-
only docstring addition explaining this exact caveat to the human reviewer: a high
`announcement_count` is not proof of real development, and the scanner's own "human evidence
inspection" step (already its documented next stage) must judge this manually. A VK-shaped fixture
was added to the golden corpus (`test_corpus_case5_vk_apple_three_publishers_reports_raw_
announcement_count`) pinning the current, unmodified `announcement_count=3` scanner output as a
regression anchor for any future correction.

## Phase 10 — Marvell reassessment

Recomputed offline (Phase 2/Phase 8 Case 2): Marvell's 3 reports are **NOT** a VK-shaped pure-
duplicate case — every pairwise combination carries a genuinely distinguishing numeric fact
(58M-share warrant vs. $12.2B valuation, further complicated by the frozen decimal-comma artifact
on the EN/RU pair). Under the (rejected, unimplemented) collapse design, Marvell's 3 clusters would
**not** have collapsed at all — the design would have correctly left them separate.

**Prospective correction to prior interpretation** (R2.9/R2.10's own record, not rewritten):
Marvell remains an excellent Story Integrity / origin-projection / cross-language fact-merging
fixture — genuinely useful evidence for those specific findings. But its `announcement_count=3`
should **not** be read as "3 real news developments" without qualification; more precisely, it
reflects 3 reports carrying 2-3 distinguishable specific facts about one underlying deal
(warrant-share-count, and a valuation figure independently corroborated once the decimal-comma fix
is applied). Whether that constitutes "readiness-worthy development" or "one deal with richer
corroborated detail" is exactly the Phase 4 Case-3 ambiguity this checkpoint deliberately left
undecided — Marvell was never confirmed READY in any prior report, and this finding does not change
that; it only sharpens *why* its `announcement_count` should be read cautiously, same as VK's.

## Phase 11 — Query/performance

Out of scope this checkpoint, per explicit instruction. Existing media N+1 (R2.10 Night 2 finding)
remains documented, unaddressed.

## Phase 12 — Test / quality gates

`tests/test_event_recap.py`, `tests/test_recap_event.py`,
`tests/test_recap_r2_9_origin_membership_projection.py`,
`tests/test_recap_r2_10_readiness_candidate_scanner.py`,
`tests/test_recap_r2_single_attempt_gateway.py`,
`tests/test_recap_r2_11_announcement_identity_forensic.py`: **151 passed, 0 failed.** Ruff clean,
mypy clean, `git diff --check` clean.

## Phase 13 — Clean checkout

Not required by the checkpoint's own condition ("if implementation is made") — no functional
implementation was made. Skipped; the test-only and documentation-only delta is small and was
validated directly in the isolated worktree.
