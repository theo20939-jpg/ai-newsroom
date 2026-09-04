# R2.10G3-A — Shadow Eventness Evaluation Report

**Status: SHADOW-ONLY, read-only. No Story Memory, RECAP readiness, publication, or DB state was
modified to produce this report.** Base: `36a1e6a46d7107b08be2cce88908666d842d38da` (G1 + G3-0).
Branch: `feature/r2-10-g3-shadow-eventness`, kept isolated from `feature/phase19-editorial-depth-
upgrade` exactly as G1/G3-0 were.

## 0. Real-DB fixture check

Before building the manifest, the exact R2.11 fixture titles (VK/Apple lawsuit, Marvell/Google
chip deal) were searched for in this database by keyword — neither exists as a real Story row here
(only unrelated stories sharing some of the same keywords were found). Both, plus the mandatory
synthetic VK 4-publisher negative control, are represented as **offline** fixtures instead — real
production titles (VK/Apple, Marvell) or a fully synthetic construction (the 4-publisher control),
built as in-memory `NewsEvent` objects exactly mirroring `feature/r2-11-announcement-identity`'s
own test construction. This never depends on any particular developer database's contents.

## 1. R212 reuse

`scripts/_recap_r2_shadow_batch.py` was copied verbatim from `feature/r2-shadow-preparation`
(commit `c799c14`) into this branch and confirmed **import-compatible with zero modification**
against base `36a1e6a` — every symbol it needs (`build_event_recap_candidate`,
`render_event_recap_bundle_text`, `scan_story_readiness`, `CandidateScanRow`) still exists at the
same path with the same signature. `build_shadow_report()` and `ShadowStoryReport` are reused
directly by the new harness (`scripts/_recap_r2_10_g3_eventness_harness.py`), not duplicated — the
new harness only adds what the batch script does not already compute: the deeper deterministic
feature set (span, match-type distribution, cluster sizes, entities), a fixed 31-fixture manifest
(vs. the batch script's own recency-ordered scan), and disagreement-flag computation against
manual ground truth.

`scripts/_recap_r2_shadow_synthesize.py` (the LLM shadow-opinion script) was **not** brought into
this branch. No LLM canary was run this phase (see §7). Bringing the script in without using it
would only add an unused, untested surface — reintroducing it is a one-line `git show` away for
whichever future phase actually runs the canary.

## 2. Dataset

31 fixtures (target: 30–40), composition:

| Manual class | Count |
|---|---:|
| TOPIC_CLUSTER | 12 |
| REAL_SINGLE_EVENT | 9 |
| DIGEST | 3 |
| EVENT_LIFECYCLE | 3 |
| NOISE | 2 |
| UNCLEAR | 2 |

28 "db" fixtures (real Story rows in this database, all 28 resolved — zero skipped) + 3 "offline"
fixtures (VK/Apple real, VK synthetic negative control, Marvell). 17 entries carry `confidence:
high` (individually forensically verified in R2.10F/R2.11); 14 carry `confidence: provisional`
(added for class balance, classified by title-read only, explicitly marked as such in the
manifest rather than presented with false certainty).

## 3. Metrics against manual ground truth

```text
evaluated_count=31, skipped_count=0
FALSE_ACCEPT_COUNT=1   (rate 0.032)
FALSE_REJECT_COUNT=10  (rate 0.323)
NEEDS_REVIEW_COUNT=3   (rate 0.097)
```

**FALSE_ACCEPT** (current readiness reads READY, manual ground truth says REJECT — the
highest-priority metric): exactly **one** case, `vk_apple_synthetic_4publisher_false_ready` — the
mandatory R2.11 negative control. This is the harness doing its job: it independently reproduces,
end-to-end through this evaluation pipeline, the exact readiness false-positive R2.11 proved by
hand. No other fixture in this 31-item sample shows this failure mode.

**FALSE_REJECT** (manual says ACCEPT, current readiness disagrees): 10 of 31 — every
`REAL_SINGLE_EVENT`/`EVENT_LIFECYCLE` fixture in the sample except `vk_apple_real_3publisher`
(which reached `ACTIVE`, not counted against it since its own desired label is `NEEDS_REVIEW`, not
`ACCEPT`). This is a genuinely important, quantified finding on its own: **current production
readiness is dramatically conservative relative to manual editorial judgment** — real events
overwhelmingly sit at `COOLING`/`REJECTED`, never `READY`, in this sample. This is expected and
by design (R2.10's own repeated finding across this whole investigation: no fixture here was ever
close to clearing announcement/source gates) — not a new defect, but useful context for whoever
designs the eventness gate itself: **a permissive deterministic pre-filter is far less risky than
it might sound**, since current readiness essentially never over-fires on its own.

**NEEDS_REVIEW**: 3 — the 2 `UNCLEAR` fixtures (Marvell, `optimizatsiya_koda`) plus
`vk_apple_real_3publisher`, exactly matching the manifest's own labels (not a system disagreement).

## 4. Class-by-class feature distributions

| Manual class | n | span_hours (min / median / max) | events (median) | announcements (median) | sources (median) | sources always 1? |
|---|---:|---|---:|---:|---:|---|
| TOPIC_CLUSTER | 12 | 44.2 / 304.0 / 494.1 | 10.5 | 6.0 | 1.0 | **yes, all 12** |
| DIGEST | 3 | 309.7 / 479.8 / 479.9 | 9.0 | 4.0 | 1.0 | no (1 of 3 has 2 sources) |
| EVENT_LIFECYCLE | 3 | 98.6 / 125.3 / 140.1 | 7.0 | 6.0 | 4.0 | no |
| REAL_SINGLE_EVENT | 9 | 0.5 / 26.2 / 283.4 | 3.0 | 2.0 | 2.0 | no |
| NOISE | 2 | 8.1 / 232.2 / 456.3 | 16.0 | 9.0 | 1.0 | yes, both |
| UNCLEAR | 2 | 2.0 / 94.9 / 187.8 | 2.5 | 2.5 | 2.5 | no |

**Observations, no threshold chosen:**
- **`unique_source_count == 1` for all 12 TOPIC_CLUSTER fixtures** — perfect separation from
  `EVENT_LIFECYCLE`/`REAL_SINGLE_EVENT` *within this sample* — but this alone is already proven
  unsafe elsewhere (R2.10G's own finding: some genuine `REAL_SINGLE_EVENT` fixtures also show
  `sources=1`, e.g. `ai_challenge_10k`, `divided_america_wire`, `ai_journey_contest` here).
- **`story_span_hours` shows real separation in the medians** (TOPIC_CLUSTER/DIGEST both median
  >300h; EVENT_LIFECYCLE median ~125h; REAL_SINGLE_EVENT median ~26h) but the *ranges overlap*
  substantially — `twitch_genai_optout` (a real single event) spans 283h, longer than two of the
  three EVENT_LIFECYCLE fixtures. Span alone would misclassify it.
- **NOISE has no consistent span signature** (8h for a wire-boilerplate digest-shaped noise case,
  456h for the GitHub-CI-bot noise case) — confirms NOISE needs a different kind of signal
  entirely (content-type, not distributional), consistent with R2.10F's own finding that the
  `ciflow_ci_noise` case passes Story Integrity and shows no numeric anomaly at all.

## 5. Hard-case report

**VLA** (`ed667801`): `readiness=COOLING`, `events=19`, `announcements=16`, `sources=1`,
`span_h=479.2`. Current readiness correctly stays far from READY (source gate). The *misleading*
signal here would be announcement_count=16 — technically correct clustering (R2.10F already
proved this), but superficially looks "developed." The *useful* signal is span (479h, deep into
TOPIC_CLUSTER's own range) combined with sources=1.

**VLM** (`78cde6c9`): same pattern, smaller scale (`span_h=90.9`, `events=6`) — notably span here
is *lower* than several other TOPIC_CLUSTER fixtures, in EVENT_LIFECYCLE's own range. A pure-span
rule would misclassify this one.

**Nvidia/HF** (`42e4188a`): `readiness=COOLING`, `events=4`, `announcements=3`, `sources=4`.
Correctly shows `CURRENT_REJECT_BUT_MANUAL_ACCEPT` — a real, incomplete event, blocked on
`announcement_count` (3 < 4), unrelated to eventness itself (G2's still-open title-case
fragmentation is the real cause, out of this phase's scope). The useful signal here is `sources=4`
— clearly un-cluster-like — but current readiness still rejects it on a different gate entirely,
which is exactly why "current readiness" cannot be treated as ground truth for eventness.

**VK/Apple false READY** (`vk_apple_synthetic_4publisher_false_ready`): `readiness=READY`,
`events=4`, `announcements=4`, `sources=4`, `span_h=0.5`. The one live FALSE_ACCEPT. Note the span:
**0.5 hours** — by far the shortest in the entire dataset. This is a real, concrete, promising
signal a future calibration phase should weigh heavily: genuine syndication happens in minutes;
even the fastest real multi-stage lifecycle here (`vk_apple_real_3publisher`, itself pure
corroboration, `span_h=0.47`) is comparably short — meaning span alone cannot distinguish
corroboration from syndication either. **Source diversity (4 unique domains) plus near-zero span is
the combination that should raise suspicion, not either signal alone.**

**Marvell** (`marvell_google`, offline): `readiness=ACTIVE`, `events=3`, `announcements=3`,
`sources=3` (previously 2 pre-G3-0, since the EN/RU pair no longer falsely conflicts — see below).
Correctly stays `UNCLEAR`/`UNCERTAIN`, per R2.11's own deliberate non-decision — this harness does
not strengthen it.

**GitHub CI noise** (`ciflow_ci_noise`): `readiness=COOLING`, `events=20`, `announcements=17`,
`sources=1`, `span_h=456.3`. Sits inside TOPIC_CLUSTER's own span/source range even though its
manual class is NOISE — confirms R2.10F's own finding that this case needs a content-type signal
(these aren't editorial titles at all), not a distributional one.

## 6. Decimal-comma fix (G3-0) verified through this harness

The Marvell offline fixture's `unique_source_count` is **3** (a.com, cnbc.com, ria.ru) under this
harness — every one of the 3 real domains counted independently, with the EN/RU $12.2B figure no
longer registering a spurious conflict between the CNBC and RIA reports. This is a live,
end-to-end confirmation that G3-0's fix is correctly inherited through the unmodified
`services/recap_event.py` call chain this harness exercises, without this phase touching that file
again.

## 7. LLM shadow path

```text
LLM_PATH_IMPLEMENTED=false (this phase)
LLM_CALLS_DURING_DEFAULT_BATCH=0
LLM_CANARY_EXECUTED=false
```

`scripts/_recap_r2_shadow_synthesize.py` was reviewed (feature/r2-shadow-preparation, commit
`1ed5043`) and found, in principle, single-Story, cost-bounded, and Telegram/publication-free by
its own existing design (see R2.10G3-P's own review of it). It was deliberately **not** brought
into this branch or run — no bounded validation canary was judged necessary to produce this
report's findings, and running one against a real paid Gateway is exactly the kind of action this
phase's own safety boundary reserves for a separate, explicit authorization.

## 8. Known limitations of this evaluation

- 14 of 31 fixtures are `confidence: provisional` (title-read classification, not individually
  forensically re-verified this phase) — real signal for composition/balance, weaker signal for
  any future numeric threshold calibration than the 17 `confidence: high` fixtures.
- The dataset skews toward AI/tech news (this database's own actual collection scope) — class
  distributions above should not be assumed to generalize to a materially different topic mix
  without re-sampling.
- `story_span_hours` and `unique_source_count` are the only two features with a visibly promising
  (if imperfect and individually already-disproven-as-sufficient-alone) separating pattern in this
  sample; `announcement_count` and `match_type_distribution` were collected but showed no clean
  separation on manual inspection - not discussed further above, but present in the raw evaluation
  JSON for a future phase to reconsider.
