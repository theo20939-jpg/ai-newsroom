# Phase 18.5 M2 — Meme Opportunity Metrics (Real Production Data)

Status: complete. All numbers below come from `python scripts/phase18_5_shadow_collection.py`
run once, read-only, against the real `ai_newsroom` database on 2026-08-05 — **12,430 real
`NewsEvent` rows, 100% successfully classified, zero failures, zero database writes** (verified:
`NewsEvent`/`EditorialTask` row counts and the zero-`meme_opportunity`-keys check from the M0
report were re-confirmed identical after this run). Raw output:
`scripts/_phase18_5_shadow_collection_results.json` (12,430 normalized records, no raw
title/content text — schema-enforced, see M1 report). Aggregates:
`scripts/_phase18_5_metrics_summary.json`.

## 1. Opportunity rate

**Formula** (brief's own): potential memes (`HIGH` + `MEDIUM`) / all analyzed news.

**Result: 0.44%** (55 potential / 12,430 total).

| Label | Count | Share |
|---|---|---|
| HIGH (`MEME_READY`) | 0 | 0.00% |
| MEDIUM (`REVIEW`) | 55 | 0.44% |
| LOW (`NOT_SUITABLE`/`INSUFFICIENT_SOURCE`) | 12,193 | 98.10% |
| BLOCKED (`SENSITIVE_BLOCK`) | 182 | 1.46% |

**This is the single most important finding of Phase 18.5.** Not one of the 12,430 real events
reached `HIGH`/`MEME_READY` (which requires a composite score ≥ 55). The composite-score
distribution explains why:

| Score bucket | Count |
|---|---|
| 10–19 | 7,539 |
| 20–29 | 4,503 |
| 30–39 | 381 |
| 40–49 | 6 |
| 50–59 | 1 |

99.97% of real events score below 40; only one event in the entire 12,430-row sample scored above
50 (and it still fell short of the 55 threshold). M1's `_READY_THRESHOLD = 55`/`_REVIEW_THRESHOLD
= 35` (`services/meme_opportunity.py`) were calibrated in Phase 18 M1 against a **13-item,
hand-picked gold set already pre-selected for containing real meme-worthy stories**
(`docs/phase18_m1_meme_opportunity_report.md`'s own disclosed limitation: "thresholds... v1,
calibrated against a 13-case hand-built gold set, not against production shadow volume"). This is
exactly the calibration gap that report predicted would need real data to close — Phase 18.5 is
that data.

## 2. Category distribution

**Among the 55 potential-meme (HIGH+MEDIUM) records**:

| Category | Share |
|---|---|
| AI | 89.09% |
| STARTUPS | 5.45% |
| UNKNOWN | 3.64% |
| SOFTWARE | 1.82% |

**Among ALL 12,430 records** (context — how this compares to raw volume, not just meme
potential):

| Category | Share of all traffic |
|---|---|
| UNKNOWN | 50.69% |
| AI | 26.03% |
| GADGETS | 7.88% |
| STARTUPS | 6.16% |
| SOFTWARE | 5.00% |
| TECH | 2.33% |
| HARDWARE | 1.72% |
| CYBERSECURITY | 0.19% |

AI is **over-represented** among potential memes relative to its own share of raw traffic (89.1%
of meme potential vs. 26.0% of all volume — a ~3.4x concentration), directly confirming Phase 18
M0's own real-data finding ("AI/STARTUPS funding-hype and founder/exec-statement stories skew
MEME_READY/POSSIBLE"). `UNKNOWN` (the single largest raw-volume category, mostly uncategorized
Telegram-sourced items) contributes almost nothing to meme potential (3.6%) despite being half of
all traffic — a real, data-backed signal that category-blind volume is a poor proxy for meme
potential, and `topic_fit_score`'s own existing `UNKNOWN` prior (35, the lowest tier) is directionally
correct.

## 3. Safety block rate

**1.46%** of all real events (182 / 12,430) were hard-blocked for a sensitivity reason.

| Sensitivity category | Count |
|---|---|
| legal_jeopardy_or_accusation | 53 |
| death_or_tragedy | 40 |
| war | 33 |
| disaster | 29 |
| crime_with_victim | 25 |
| harassment_or_stalking | 5 |
| protected_characteristics | 3 |
| minors_safety | 2 |

Every category the safety lexicon defines fired at least once against real traffic — none is
dead code. `legal_jeopardy_or_accusation` (named individuals in legal/extremism-registry contexts)
and `death_or_tragedy` are the two largest real contributors, consistent with this being a mixed
tech+general-news firehose (several ingested sources cover broader current events, not only pure
tech), not an artifact of the lexicon being miscalibrated toward one narrow category.

## 4. Pattern performance

Real evidence-code firing frequency among the 55 potential-meme records:

| Pattern | Count |
|---|---|
| contradiction | 48 |
| emotional_contrast | 16 |
| irony | 6 |
| unexpected_result | 1 |

`contradiction` (the `contrast_connector` marker — words like "несмотря на"/"however"/"despite")
is by far the most common real signal, firing in most potential-meme records. `unexpected_result`
(the `hype_without_substance` marker — large funding sums with no shipped product) fired only
once in this real sample — a real, data-backed sign that this specific pattern, while
theoretically sound (and validated in Phase 18 M1's own hand-built test cases), is genuinely rare
in this news source mix, not a bug.

## 5. Source sufficiency (context for the LOW-label breakdown)

| Value | Share of all records |
|---|---|
| sufficient | 46.00% |
| partial | 29.60% |
| headline_only | 24.37% |
| empty | 0.03% |

Of the 12,193 `LOW`-labeled records, 3,010 (24.7%) were `LOW` specifically because of thin source
content (`headline_only`/`empty` — `INSUFFICIENT_SOURCE`), while the remaining 9,183 (75.3%) had
adequate source content but simply scored below the composite threshold
(`composite_below_review_threshold`) — confirming the low opportunity rate is driven mainly by
genuinely low irony/relatability/topic-fit scores on ordinary news, not by a source-thinness
artifact.

## 6. False positive tracking — foundation only (per the brief's own M2 scope)

`schemas.meme_shadow_analytics.MemeHumanReviewDecision` (a 4-value taxonomy:
`good_meme_candidate`/`weak_candidate`/`not_a_meme`/`unsafe`, mirroring Phase 18 M9's own
`MemeRejectionReason` taxonomy shape) is added as the schema a human reviewer will use in M3 — not
populated by any code in M2. No false-positive **rate** can be computed yet; that requires the
human review this phase's own M3 packet exists to collect.

## 7. What this means for M1's thresholds (forward pointer to M4)

The real data suggests `_READY_THRESHOLD`/`_REVIEW_THRESHOLD` may be miscalibrated for this
project's actual news mix — but this report does **not** recommend changing them unilaterally.
Two competing readings of the same data are both defensible without human review to arbitrate:
(a) the thresholds are too strict, and a genuinely good meme candidate is being scored `LOW`
somewhere in the 12,193; or (b) the thresholds are appropriately conservative for a system whose
own M0 report explicitly prioritized "recall favored over precision... a false block is cheaper
than a false pass," and 55 real `MEDIUM` candidates from one day's backlog is a perfectly
reasonable, small, human-reviewable shortlist. M3's human review packet is built specifically to
distinguish these two readings with real judgment, not more heuristics.
