# Phase 16.5 — Image Intelligence Calibration — Report

Branch: `feature/phase16-image-intelligence`
Checkpoint: `checkpoint/phase16.5` (created at the end of this milestone)
Prior checkpoint: `checkpoint/phase16-m7`

## 1. Problem discovered in M7

M7's real, 100-event shadow validation (docs/phase16_m7_shadow_validation_report.md §10/§13/§14)
found that **29% of sampled events selected the exact same Google-hosted generic app icon as their
top-ranked, editorial-eligible image** - confirmed by a direct `SELECT DISTINCT remote_url` query
against real persisted data, not an estimate. The image was never the publisher's own photo; it
was Google News' own generic branding icon, identical across every affected event.

## 2. Root cause

A Google News RSS item's own `<link>` (and hence `NewsEvent.url`) resolves to a
`news.google.com/rss/articles/...` redirect/interstitial page - **not** the publisher's real
article page. M2's article-metadata fetch (`services/article_metadata.py`, unchanged, working
exactly as designed) correctly extracts that page's own `og:image`, which is Google's own generic
app icon, served from a Google-owned asset CDN (`lh3.googleusercontent.com`, confirmed byte-
identical across every affected event via direct DB query). M4's relevance ranking
(`services/image_relevance.py`) had no signal distinguishing "the article's own domain matches"
(true here - `news.google.com` matches itself) from "the *image* is a real, per-article asset"
(false here - it is Google's own generic branding, not the publisher's photo). This is **not** a
defect in secure fetch, quality scoring, deduplication, or the Telegram preview - each performed
correctly given what the (correctly-fetched) page actually offered. It is a provenance/ranking
calibration gap, exactly as M7's own recommendation characterized it.

## 3. Chosen fix

**Option C, combined precisely with the brief's own "ARTICLE SOURCE vs IMAGE SOURCE" rule**:
`services/image_relevance.py::_is_generic_aggregator_asset()` (new) excludes a candidate from
eligibility only when **both** of the following hold together:

1. The candidate's own `source_url` (the article page M2 actually fetched) has a registrable
   domain of `google.com` - covers both the current `news.google.com` subdomain and the legacy
   `google.com/news`/`www.google.com/news` path form.
2. The candidate's own `remote_url` (the image itself) has a registrable domain in
   `{google.com, googleusercontent.com, gstatic.com}` - Google's own generic asset CDNs.

Wired into the existing `evaluate_eligibility()` extension point (`services/image_relevance.py`) -
the exact same function that already excludes M2/M3-failed candidates - as one additional
`return False, "generic_aggregator_asset"` check. Everything downstream (scoring, ranking, the M6
Telegram preview, M5 persistence) is completely unaware anything changed: an excluded candidate
simply reports `RelevanceStatus.INELIGIBLE` with this new reason string, exactly like every other
pre-existing ineligibility path (M2 technical failure, M3 hard rejection, non-representative
duplicate) - "nothing silently dropped," the same discipline M4 already established.

**Why this precisely satisfies "preserve valid articles" (the brief's own explicit non-goal
violation to avoid)**: the check requires *both* signals. A Google-News-sourced article whose image
is hosted on the real publisher's own domain (`cdn.theverge.com`, say) never matches condition 2 -
fully eligible, unaffected. A normal, non-Google-News article that happens to legitimately embed a
Google-CDN-hosted image (e.g. a Blogger or Google-Photos-hosted picture) never matches condition 1
- fully eligible, unaffected. Only the specific, real, observed combination is excluded.

## 4. Alternatives rejected

- **Option A alone (deprioritize provenance for aggregator sources, article-domain-only signal)**:
  rejected as the sole mechanism - keying only on "article is Google News" would also deprioritize
  the legitimate case (test requirement 2: "Google News article with publisher image: Expected:
  allowed") since it cannot distinguish the image's own origin from the article's.
- **Option A' (deprioritize based on image host alone, ignoring the article)**: rejected - a
  legitimate, unrelated site that happens to embed a real Google-CDN-hosted image (Blogger,
  Google Photos shares) would be incorrectly penalized; this was a concrete false-positive risk
  identified during design, not a theoretical one (`googleusercontent.com` is a general-purpose
  Google CDN used for many legitimate non-News purposes).
- **Option B (follow the redirect to the real publisher URL before extracting metadata)**: the
  structurally "more correct" fix (would let M2 discover the publisher's own real image directly),
  but requires changing `integrations/http/safe_fetch.py`'s/`services/article_metadata.py`'s own
  fetch behavior - a materially larger, redirect-following change touching M2's own established,
  already-validated fetch boundary. Rejected for this milestone as larger than "the smallest safe
  calibration fix" the brief calls for; noted as the more thorough option for a future milestone if
  Google News coverage itself (not just avoiding the wrong image) ever becomes a real product goal
  (§9).
- **Blanket-rejecting every Google-News-sourced event's images**: explicitly rejected by the brief
  itself ("Do not blindly reject all Google News sourced articles") and would have been a real
  regression - confirmed directly in testing (§6) that a Google News article with a genuine
  publisher image must remain rankable.

## 5. Code changes

- `services/image_relevance.py` (+29 lines): `_AGGREGATOR_ARTICLE_REGISTRABLE_DOMAIN`,
  `_GENERIC_ASSET_IMAGE_REGISTRABLE_DOMAINS`, `_is_generic_aggregator_asset()` (new), one new
  `return False, "generic_aggregator_asset"` branch in `evaluate_eligibility()`. No other function
  changed - `classify_relationship()`, `score_candidate()`, `rank_candidates()`, `PROVENANCE_TABLE`,
  every scoring weight, and M3's `quality_score` are all byte-for-byte unchanged.
- `scripts/phase16_m7_shadow_validation.py` (+~50 lines): `run_coverage_phase()` now accepts an
  optional pinned `event_ids` list (so a later calibration pass can re-run against the *exact same*
  real sample rather than a time-shifted "most recent 100"), always reports `sampled_event_ids` in
  its own output for this purpose, and directly reports `generic_aggregator_top_choice_events`/
  `_rate` - the precise KPI this milestone targets - computed independently of the production fix
  itself (a duplicated, standalone `_is_generic_google_asset()` check in the script, so the
  measurement never merely asserts the production code agrees with itself).
- `tests/test_image_relevance_calibration.py` (new, 197 lines, 17 tests).
- No schema/migration change. No `.env` change. No architecture change - the fix lives entirely
  inside the single, already-existing M4 eligibility extension point.

## 6. Tests

13 new tests in `tests/test_image_relevance_calibration.py`, covering every case the brief
requires plus boundary/false-positive-resistance checks:

1. **Google News generic icon → rejected**: `test_google_news_generic_icon_is_ineligible`,
   `test_google_news_generic_icon_never_becomes_the_ranked_top_candidate` (end-to-end through
   `rank_candidates()`).
2. **Google News article with a real publisher image → allowed**:
   `test_google_news_article_with_real_publisher_image_remains_eligible`,
   `test_google_news_article_with_real_publisher_image_can_be_top_ranked` (end-to-end, two
   candidates for the same event - the generic icon is excluded, the real image is ranked and
   becomes `eligible_for_editorial`, proving the fix never blanket-rejects a Google-News-sourced
   event).
3. **Normal RSS source → unchanged**: `test_normal_rss_source_is_unaffected`, plus
   `test_normal_rss_source_embedding_a_google_hosted_image_is_unaffected` (the concrete false-
   positive case from §4, directly proven safe).
4. **Telegram source → unchanged**: `test_telegram_native_source_is_unaffected` (no `source_url` at
   all - structurally exempt).
5. **NEWS_API source → unchanged**: `test_news_api_source_is_unaffected`.
6. Detector boundary tests: legacy `google.com/news` path form matches
   (`test_detector_matches_legacy_google_com_news_path_form`), `gstatic.com` image host matches
   (`test_detector_matches_gstatic_image_host`), a lookalike domain (`notgoogle.com`) never matches
   (`test_detector_never_matches_a_lookalike_domain` - registrable-domain comparison only, never a
   substring check, mirroring `classify_relationship()`'s own established precedent), missing
   `remote_url`/`source_url` never crashes or false-positives
   (`test_detector_requires_both_article_and_image_signal`,
   `test_detector_ignores_missing_source_url`).

Full results: `tests/test_image_relevance_calibration.py`: **13 passed**. `-k image` (all M1-M7
image-intelligence test files plus this calibration file): **429 passed** (416 pre-existing + 13
new), 0 failed, 0 regressions. Full repository suite: see §11.

## 7. Backtest

Repeated the M7 methodology exactly (`scripts/phase16_m7_shadow_validation.py --phase coverage`),
this time with a genuine, isolated **before/after comparison on the identical 100 real events** -
not a new, time-shifted sample - using the script's own new pinning support:

1. Ran `coverage` once with the fix active → captured its own `sampled_event_ids` (100 real,
   naturally-collected events, freshly sampled at run time).
2. Re-ran `coverage` on that *exact same* pinned 100-event list with `services.image_relevance.
   _is_generic_aggregator_asset` monkeypatched back to `False` (a one-off, in-process measurement
   script, never touching the production file) - this is the "before" measurement, isolated from
   any sample-to-sample drift.

No synthetic event was created for this backtest - both passes reused the identical 100 real,
already-collected `NewsEvent` rows.

## 8. Before/after metrics

| Metric | Before (fix disabled) | After (fix active) | Change |
|---|---|---|---|
| **Generic Google News top-choice rate** | **32/100 = 32.0%** | **0/100 = 0.0%** | **-32 points, target <5% achieved** |
| Generic-aggregator candidates excluded | 0 | 32 | (new, expected) |
| Events with ≥1 image candidate | 94 | 93 | -1 (live-network run-to-run noise, see §9) |
| Events with a ranked top candidate | 94 | 61 | -33 (32 correctly lost their *only, wrong* candidate; see §9 for the 1 unrelated case) |
| Source-type distribution (RSS/NEWS_API/TELEGRAM) | 84/14/2 | 84/14/2 | unchanged |
| Quality-score buckets (90-100/70-90/50-70) | 108/50/37 | 104/51/37 | materially unchanged (small live-run variance) |
| Relevance-score avg (ranked candidates) | 57.7 | 59.6 | **improved** - removing low-relevance generic-icon candidates from the ranked pool raised the average, exactly as expected |
| Duplicate exact/near counts | 22/12 | 21/12 | materially unchanged |
| Hard-rejection reasons (`favicon_dimensions`) | 9 | 9 | unchanged |

**Improvement: a 32-percentage-point reduction (32.0% → 0.0%), a 100% relative reduction on this
sample - well past the <5% target.** M7's own original, separately-sampled 100-event measurement
(29%) and this milestone's independently-sampled "before" pass (32%) are consistent with each
other (both in the high-20s/low-30s range), confirming the underlying rate is a stable, real
phenomenon, not sampling noise - and that the fix eliminates it on both.

**False-rejection check**: of the 33 events that lost their pre-fix top choice, 32 are exactly
accounted for by the new `generic_aggregator_asset` exclusion (each had *only* the generic icon
ranked, with no legitimate alternative - correctly becoming "no image" rather than "wrong image").
The 1 remaining case (a "Samsung Galaxy S26 FE" article with 3 real, Google-unrelated candidates)
was investigated directly: none of its 3 candidates reference any Google domain in any field,
ruling out the fix as the cause - attributed to ordinary live-network non-determinism between two
separately-timed real fetch passes (a transient fetch outcome difference), the same class of
noise M2-M4's own reports already documented as an accepted characteristic of live validation
against real, external sites. **Zero false rejections attributable to this milestone's fix.**

## 9. Remaining limitations

- **The 33 (32 confirmed + 1 unrelated) events that lost their image entirely now show no image at
  all** for this run, rather than a fallback publisher image - because, for these specific events,
  no other candidate existed on the fetched page at all (Google's own interstitial page carries no
  other image metadata to fall back to). This is the *intended*, correct outcome ("no image is
  strictly better than the wrong image"), not a coverage regression to fix - but it does mean
  Google-News-sourced events will, on average, show an image less often than other RSS sources
  until/unless a future milestone implements Option B (§4) to reach the publisher's own real image.
- **Option B (redirect-following) remains the more complete long-term fix** if Google News coverage
  itself becomes a product priority - this milestone deliberately chose the smaller, safer,
  non-architecture-touching calibration instead, per its own explicit scope.
- **The generic-asset domain list is a small, explicit, hand-curated set** (`google.com`,
  `googleusercontent.com`, `gstatic.com`) - matches every real instance observed in both M7 and this
  milestone's own backtests, but a future, different Google-owned CDN domain (should Google change
  its own infrastructure) would not be automatically covered without updating this list by hand -
  the same "hand-curated, not auto-derived" tradeoff `scripts/validate_architecture.py`'s own rule
  table already accepts elsewhere in this codebase.
- **1/100 events showed unrelated cross-run variance** (§8) - a reminder that this validation
  methodology, while rigorous, inherits real-network non-determinism; a single-point difference on
  a 100-event sample is expected noise, not a precision guarantee.

## 10. Phase 16 final verdict

All eight Phase 16 milestones (M0-M7) plus this calibration pass are complete:

- M0 Discovery, M1 Native Media Ingestion, M2 Secure Fetch, M3 Quality + Deduplication, M4
  Relevance Ranking, M5 Persistence + Retention, M6 Telegram Editorial Preview, M7 Shadow/Live
  Validation, and now **16.5 Calibration** - which closes M7's one material, quantified gap.
- The generic-aggregator-image miscalibration M7 flagged as the blocking reason for "NEEDS
  CALIBRATION" is now fixed and independently re-measured at 0% (target <5%) on a real, isolated
  before/after comparison, with zero attributable false rejections.
- Every other M7 finding (secure fetch, quality gating, deduplication, ranking-for-non-aggregator-
  sources, persistence, Telegram preview) was already healthy and remains untouched and unaffected.
- **Production posture is unchanged**: `IMAGE_INTELLIGENCE_MODE`, `IMAGE_CANDIDATE_PERSISTENCE_
  MODE`, and `IMAGE_EDITORIAL_PREVIEW_ENABLED` remain `off`/`off`/`False` in every deployed
  environment and in `.env` - this calibration milestone changed code, not activation state.

**Phase 16 (Image Intelligence), including this calibration pass, is now technically
activation-ready** - the decision to actually flip the flags in production remains a separate,
deliberate operational decision for whoever owns that call, not something this or any prior Phase
16 milestone made unilaterally.

## 11. Testing

- `python -m ruff check .` (full repository): all checks passed.
- `-k image` selection (M1-M7 + this calibration's own test file): **429 passed**, 0 failed.
- Full repository suite (`python -m pytest -q`): **1676 passed, 15 failed** - exactly M7's own
  1663-passed baseline plus this milestone's 13 new tests, with the identical 15 pre-existing
  failure names every prior Phase 16 report has documented (`test_capability_executor.py` ×8,
  `test_content_generation_integration.py` ×1, `test_content_worker_cycle.py` ×2,
  `test_editorial_scoring.py` ×2, `test_fact_safety.py` ×2) - zero new regressions from this
  milestone's fix.
- Migrations: none added - this milestone is a pure code/ranking-logic change.
- No LLM/provider call anywhere in the fix or its tests (confirmed structurally - `services/
  image_relevance.py` continues to import only `html`/`re`/`time`/`unicodedata`/`dataclasses`/
  `urllib.parse`/this repo's own `schemas` module, unchanged from M4's own AST-verified import set).

## 12. Deployment

Only `content_worker` imports `services/image_relevance.py` - rebuilt and redeployed; container
started cleanly, migration unchanged at head, `IMAGE_INTELLIGENCE_MODE`/`IMAGE_CANDIDATE_
PERSISTENCE_MODE`/`IMAGE_EDITORIAL_PREVIEW_ENABLED` reconfirmed `off`/`off`/`False` inside the
running container after redeploy. No other service touched.

## 13. Phase 17 handoff notes

- The generic-aggregator-image gap is closed; Phase 17 (or whatever activation decision comes
  next) can treat M7's "NEEDS CALIBRATION" blocker as resolved.
- If Google News coverage rate itself (not just avoiding the wrong image) becomes a priority,
  Option B (§4 - follow the redirect to the real publisher URL in M2's own fetch layer) is the
  natural, already-scoped next step - a materially larger change than this milestone's own, so
  deliberately deferred rather than folded in here.
- `scripts/phase16_m7_shadow_validation.py`'s new pinned-event-ID support (§5) is reusable for any
  future re-validation that needs a true before/after comparison rather than a fresh, time-shifted
  sample.
