# Paid-Candidate Volume Audit (Step 6)

Status: **AUDIT COMPLETE. One volume-reduction opportunity IDENTIFIED AND QUANTIFIED, NOT
IMPLEMENTED** — deliberately deferred as a proposal, not a live change, for the reasons in §4.

## 1. The funnel (real 3-day counts, Postgres, durable)

| Stage | Count | % of collected |
|---|---|---|
| Total collected (`news_events`) | 3759 | 100% |
| Never got any `EditorialTask` (deterministic triage rejection - malformed title, etc.) | 5 | 0.13% |
| Queued for `NEWS_ANALYSIS` (`CREATED`, not yet run) | 3285 | 87.4%* |
| `NEWS_ANALYSIS` `COMPLETED` | 421 | 11.2% |
| `NEWS_ANALYSIS` `FAILED` | 228 | 6.1% |
| Eligible for / reached `CONTENT_GENERATION` | 26 | 0.69% |
| Delivered (real `ContentDraft`, `COMPLETED` `CONTENT_GENERATION`) | 26 | 0.69% |

\* Backlog, not daily-flow-representative — see `docs/api_cost_audit_report.md` §1: this is
almost entirely a symptom of the OpenAI quota outage (zero throughput since 2026-07-25 22:04
UTC), not evidence that 87% of collected events "should" queue this long under normal operation.

**Deterministic rejection before `NEWS_ANALYSIS` is essentially zero (0.13%)** — confirmed
directly: only 5 of 3759 collected events in this window never received an `EditorialTask` at
all. Every other collected event, regardless of source, category, or apparent relevance, is
queued for the full 4-call `NEWS_ANALYSIS` treatment.

## 2. Where the volume actually comes from

```
source                                  events (3 days)
Google News RU: ИИ                      313
Google News: Artificial Intelligence    260
3DNews                                  139
9to5Mac                                 129
9to5Google                              113
Hacker News Front Page                  107
arXiv cs.LG                             100
arXiv cs.AI                             100
arXiv cs.CV                             100
arXiv cs.CL                             100
```

Two Google News topic-aggregator feeds + four arXiv paper-listing feeds together account for
**1340 of 3759 collected events (35.6%)** in this window. All 6 are also among the sources
driving `category = UNKNOWN` (2837 of 3759 events, 75.5%, overwhelmingly explained by these
same high-volume feeds never having been tagged by Phase 15 M2's deterministic source-tag
mapping — a category *data-quality* gap, not itself a cost gate).

**Source reliability is not a usable additional filter today**: every currently-configured
source has `reliability_score >= 0.68` (verified: `SELECT DISTINCT reliability_score FROM
sources` via the events in this window) — there is no "known-bad" source in the current catalog
a reliability floor could exclude. This rules out reliability-score as a lever without first
deciding new, lower scores for specific sources (a data decision, not a code one, and outside
this audit's evidence).

## 3. Quantified opportunity (not implemented)

If the 6 highest-volume, lowest-editorial-specificity feeds above (2 broad news aggregators + 4
academic paper listings) were excluded from `NEWS_ANALYSIS` entirely via a deterministic,
explicit source-name/id denylist (the same kind of static, hand-maintained list this codebase
already uses for source-tag category mapping — no new scoring architecture, no new heuristic,
just an explicit exclusion set):

- **Potential `NEWS_ANALYSIS` call-volume reduction: ~35.6%** of collected events, which —
  since `NEWS_ANALYSIS` is 94.2% of total call-count spend (`docs/api_cost_audit_report.md`
  §4) — projects to roughly **35.6% × 94.2% ≈ 33.5% of total spend**, a substantial additional
  lever on top of Steps 2-4.

## 4. Why this is a documented proposal, not a live change, in this task

1. **Genuine editorial risk, not yet characterized.** arXiv papers and Google News aggregator
   items are not inherently low-value — a real, newsworthy AI research breakthrough or a major
   story a topic-aggregator surfaces first could legitimately be exactly what this pipeline
   exists to catch. Excluding these feeds wholesale is an editorial-scope decision, not a purely
   technical one, and this task's own instruction is explicit: *"Do not silently change the live
   rate until before/after volume and quality are documented."* No "after" quality sample can be
   collected without actually running the change, which this task's $0.50 paid-validation budget
   and the ongoing quota outage (`docs/api_cost_audit_report.md` §1) both make infeasible right
   now.
2. **The already-implemented levers (Steps 2-4) are lower-risk and already deliver most of the
   target reduction** (`docs/api_cost_optimization_report.md` §13's projection) without touching
   editorial scope at all — routing and duplicate-call removal reduce *cost per call*, not *which
   stories get analyzed*, so they carry none of this risk.
3. **Recommended next step, explicitly not taken here**: pilot excluding 1-2 of the 6 feeds
   (not all 6 at once), observe a bounded natural sample of what would have been analyzed vs.
   skipped, and have an editorial reviewer (not an automated quality metric) judge whether
   anything genuinely valuable was missed — the same bounded-natural-sample discipline already
   used throughout this project for Editorial Scoring V2 and Fact Safety.

**No code was changed for this step.** Triage/Collector behavior, priority assignment, and
category-tag mapping are all byte-for-byte unchanged.

---

**VOLUME AUDIT COMPLETE — LARGEST ADDITIONAL LEVER IDENTIFIED (~33% OF SPEND), DELIBERATELY NOT
ACTIVATED PENDING EDITORIAL REVIEW**
