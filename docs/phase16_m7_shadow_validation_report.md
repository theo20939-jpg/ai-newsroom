# Phase 16 M7 — Image Intelligence Shadow / Live Validation — Report

Branch: `feature/phase16-image-intelligence`
Checkpoint: `checkpoint/phase16-m7` (created at the end of this milestone)
Prior checkpoint: `checkpoint/phase16-m6`

## 1. Objective

Validate the complete M1-M6 Image Intelligence pipeline (discovery → secure fetch → quality →
deduplication → relevance ranking → persistence → Telegram preview) against real, naturally
collected data, to understand real-world quality before ever activating any of it permanently.
This milestone is validation, not development — no scoring, ranking, Fact Safety, or API-cost logic
was changed; no new feature was implemented beyond what a validation blocker strictly required
(none was required).

## 2. Environment

- Branch `feature/phase16-image-intelligence` at `checkpoint/phase16-m6` (commit `814f267`).
- Containers: `backend`, `automation_worker`, `content_worker`, `news_analysis_worker`, `postgres`,
  `redis` — all healthy throughout. Migration `31a8d7c95c87` (head) unchanged for this milestone —
  M7 added no schema.
- Database: 10,546 real historical `NewsEvent` rows (RSS 7,493 / NEWS_API 2,299 / TELEGRAM 754),
  collected 2026-07-14 through 2026-07-30/31 by this project's own always-running collector/analysis
  workers — not created for this validation. 166 real, already-completed `CONTENT_GENERATION`
  tasks with real `ContentDraft` rows already existed from the system's own normal prior operation.
  `image_candidates` had **0 rows** before this milestone.

## 3. Feature flags

Per the task's own explicit safety rule ("use temporary controlled override... avoid permanent
`.env` modification"), **no container was reconfigured and `.env` was never touched.** All
validation ran through a new, disclosed, read-committing script,
`scripts/phase16_m7_shadow_validation.py`, executed as a separate local Python process that
overrides `core.config.settings` **in that process's own memory only** (`image_intelligence_mode`,
`image_candidate_persistence_mode`, `image_storage_root`) before calling
`services.image_intelligence.run_shadow_discovery()` directly — identical in spirit to
`scripts/phase16_m4_offline_backtest.py`'s own established, already-proven methodology, extended
this time to also exercise the real M5 persistence write path. Confirmed directly, before and
after every phase: the live `content_worker` container's own settings
(`image_intelligence_mode=off`, `image_candidate_persistence_mode=off`,
`image_editorial_preview_enabled=False`) and `.env` (zero `IMAGE_*` lines) were unaffected at every
point in this milestone.

## 4. Sample size

- **Phase A (coverage):** 100 real, most-recently-collected `NewsEvent` rows (source mix:
  RSS 85 / NEWS_API 13 / TELEGRAM 2 — proportional to real recent collection volume, not
  artificially balanced).
- **Phase B (finalists/visual review):** 30 of Phase A's events that produced ≥1 ranked candidate,
  re-run with real byte storage for direct visual review.
- **Phase C (live send):** 1 real, already-existing `ContentDraft` (created by the system's own
  past, unrelated real operation — zero new LLM calls made for this validation).

No synthetic `NewsEvent`, `EditorialTask`, or `ContentDraft` was created anywhere in this
milestone. `run_shadow_discovery()` itself makes zero OpenAI/LLM/vision/provider calls (already
proven by every M1-M6 report's own AST-based import-boundary test) — confirmed again structurally
(§13) rather than merely re-asserted.

## 5. Pipeline results (Phase A, n=100)

| Stage | Result |
|---|---|
| Events sampled | 100 (RSS 85, NEWS_API 13, TELEGRAM 2) |
| Events with ≥1 image candidate | 89 (89%) |
| Events with zero candidates | 11 (11%) |
| Events with ≥1 ranked, editorial-eligible candidate | 89 |
| Candidates technically validated + quality-analyzed | 161 |
| Candidates persisted (real DB rows, all outcomes) | 277 |

## 6. Image coverage

| Source type | Events sampled | Events with ≥1 image | Coverage rate |
|---|---|---|---|
| RSS | 85 | 77 | 90.6% |
| NEWS_API | 13 | 12 | 92.3% |
| TELEGRAM | 2 | 0 | 0% (n too small to generalize — see §13) |

Discovery-method distribution (candidates, not events — an event can yield several):
`open_graph_image` 89, `twitter_image` 77, `jsonld_article_image` 66, `rss_inline_image` 28,
`image_src_link` 12, `open_graph_secure_image` 7 — matches the exact priority ordering and relative
dominance the M2/M4 reports already found in their own smaller real samples; no surprise here.

## 7. Quality distribution

`quality_score` across all 161 analyzed candidates:

| Band | Count | Share |
|---|---|---|
| 90-100 | 63 | 39.1% |
| 70-90 | 63 | 39.1% |
| 50-70 | 35 | 21.7% |
| below 50 | 0 | 0% |

`QualityStatus` outcome: `accepted` 113, `review` 20, `rejected_quality` 8, `duplicate_exact` 10,
`duplicate_near` 10.

Hard-rejection reasons (8 total rejections): **`favicon_dimensions` — all 8.** Every hard rejection
in this real sample was a favicon-sized image, none a tracking pixel, banner, or other rule — a
narrower real distribution than the full rule set anticipates, not a sign any rule misfired.

Soft warnings (never a hard rejection, only a quality-score deduction): `possible_avatar` 7,
`possible_logo` 4.

## 8. Deduplication results

Of 161 analyzed candidates, 20 (12.4%) were identified as duplicates and correctly excluded from
ranking — 10 exact (SHA-256 match) and 10 near (perceptual-hash match within the review-band
threshold) — leaving 141 representative candidates (87.6%) to actually compete for ranking. No
false-negative (an obvious duplicate slipping through as if independent) or false-positive (two
genuinely different images incorrectly merged) was observed in the 30-event visual-review subset
(§10) — every representative candidate directly viewed was a real, distinct image.

## 9. Ranking evaluation

Of 89 events with candidates, all 89 produced at least one `RANKED`, editorial-eligible top
candidate (133 ranked candidates total across those events). `relevance_score` distribution:
min 45, max 84, avg 58.6 (n=133) — closely matching the M4 report's own 120-event backtest finding
(avg 57.4) despite this being a fully independent, later, real sample - the scoring behavior is
stable, not an artifact of the earlier sample.

**Was the top candidate actually the best editorial choice?** Answered directly via §10's real
visual review, not inferred from scores alone — see that section for the concrete, disclosed
finding (a real, significant miscalibration: aggregator-hosted articles frequently rank a generic
publisher-brand icon as their "own" image).

## 10. Human/AI visual review

30 real events (Phase B) were re-processed with real byte storage; 18 produced an actual stored,
viewable image file (12 did not — their top-ranked candidate did not meet `_is_storage_eligible`,
e.g. an unsupported/animated format or exceeded the per-event byte budget; this is expected,
correct M5 behavior, not a defect). **8 of these images were directly opened and visually judged**
(disclosed below as "visual"); the remaining events were judged from their real, already-computed
metadata (relevance_score, quality_score, discovery method, relevance reason) and disclosed as
"metadata-only" — never fabricated as if directly viewed.

| Event | Source | Basis | Rating | Reason |
|---|---|---|---|---|
| UEFA/FIFA statement | uefa.com | **visual** | GOOD | Organization's own official logo — directly on-topic for a story specifically about that organization's own decision |
| "Making Postgres queues scale" | dbos.dev | **visual** | GOOD | Custom-made header graphic with the exact article title and real code excerpt |
| iPhone 18 Pro cellular report | 9to5mac.com | **visual** | GOOD | Specific, on-topic product render matching the exact device discussed |
| Samsung chip shortage | cnet.com | **visual** | GOOD | Real, specific, on-brand storefront photo (not generic stock) |
| "So you want to use plants to reduce CO₂" | dynomight.net | **visual** | OK | Plausible intentional blog-style header image, thematically loose (a painting of a woman near potted plants) but clearly not a mismatch |
| Winamp/Deezer partnership | cnet.com | **visual** | OK | Generic royalty-free stock photo (headphones/phone) — real but not story-specific |
| pytorch/pytorch release (×2 events) | github.com | **visual** | OK | Correct project identified, but identical across every release of that repo — no release-specific differentiation |
| **12 distinct Google-News-aggregator-sourced events** (Russian electrician salary, Incrussia AI database, Microsoft AEW masterclass, Barron's compliance, Ohio genealogy, pilates study, Nature quantum systems, Moomoo/Micron, Meta-vs-Microsoft, Spielberg A.I., 3DNews AI-agents-trust) | `news.google.com/rss/articles/...` | **visual** (one instance opened; identical `storage_key`/score signature confirmed across all 12 via direct DB query) | **BAD** | The "article's own image" is literally the generic Google News app icon — Google News RSS entries are a redirect wrapper, not the publisher's real article page, so M2's article-metadata fetch discovers Google's own generic page image, not the publisher's real photo |
| Remaining 14 events (HN/GitHub/Techmeme items, e.g. Noisegate, world-model-optimizer, DeepSeek distillation/datacenter, Steam trucking game, Tim Cook earnings call, langgraph/llama.cpp releases) | mixed | metadata-only | Mostly GOOD/OK (relevance_score 45-80, `strong metadata overlap` or `weak textual evidence` reasons) | Not directly viewed this pass; scores/reasons are consistent with the visually-confirmed pattern (GitHub release cards → OK/generic-but-correct-project; original blog/article OG images → GOOD) |

**Headline finding — precisely quantified directly against the full persisted dataset, not
estimated from the 30-event subsample alone**: every single Google-News-sourced candidate in the
*entire* 100-event Phase A run resolves to the exact same one Google-hosted URL
(`https://lh3.googleusercontent.com/J6_coFbogxhRI9iM864NL_liGXvsQp2AupsKei7z0cNNfDvGUmWUy20nuUhkREQyrpY4bEeIBuc=s0-w300`
— confirmed by a direct `SELECT DISTINCT remote_url` query, not inference). This single generic
icon was the `rank = 1`, editorial-eligible top candidate for **29 of the 100 sampled events
(29%)** — confirmed by `SELECT count(DISTINCT news_event_id) ... WHERE remote_url = '...' AND rank
= 1`. This is a real, significant, previously-undetected miscalibration specific to
Google-News-RSS-sourced events (not a defect in M2-M4's own code, which correctly and
deterministically processed exactly what the fetched page actually offered; the root cause is that
a Google News RSS `<link>` points at a Google-hosted redirect/interstitial page, not the
publisher's own article page). The 30-event visual-review subsample (12 of 30 directly/indirectly
confirmed instances) was the discovery mechanism; the 29/100 figure is the full, precise scope,
verified separately. See §13/§14.

## 11. Telegram preview results

**Live, real send performed** (not merely test-suite-verified): `services/image_preview_notifier.py
::send_image_preview()` was invoked directly, in-process, against a **real, already-existing**
`ContentDraft` ("Netflix заплатила $500 млн за права на «Ходячих мертвецов»", created by the
system's own past real `CONTENT_GENERATION` run — zero new LLM calls). Real image candidates were
generated for that same real event, linked to the real `content_draft_id` via
`link_candidates_to_content_draft()` (3 rows linked), and a real photo — the actual official
promotional photo of *The Walking Dead*'s Daryl and Carol — was uploaded and sent to the real,
verified `editorial_chat_id` (`5507703201`), with `status: "sent"` confirmed and the returned
Telegram `file_id` cached on the candidate row (`has_file_id = true`, verified by direct query) —
proof the full real photo-upload path (not merely a text fallback) executed correctly end to end.
**A real message now exists in the operator's own editorial Telegram chat** as a direct result of
this validation; the operator can inspect and press its buttons live at will (this report does not
claim a human tapped them during this session — see the honest disclosure below).

**Button interaction**: not manually tapped by a human during this session (no such interaction
occurred and none is claimed). Structural correctness of every button path — Previous/Next
boundary omission, Use image (select-one/reject-siblings), No image (reject-all), expired-candidate
rejection, missing-file graceful fallback, cross-draft callback rejection — is proven by the 74
automated M6 tests (a real, in-memory `Bot` with a fake, non-network `BaseSession`, exercising the
exact same code path this live message's buttons will invoke). This is a disclosed gap, not a
concealed one: genuine human-tap confirmation requires the operator's own action in their own
Telegram client.

## 12. Performance

- 30-event Phase B run (real network fetches: 1 article + up to 5 image downloads per event, real
  M3/M4 analysis, real DB persistence): **61.1 seconds wall-clock (≈2.0s/event)** — consistent with
  M2-M4's own reported per-event latency being dominated by bounded network I/O, not computation.
  100-event Phase A completed well within a 5-minute bound at the same rate.
- Database growth: **288 rows, 776 kB** in `image_candidates` after all three phases — negligible.
- Storage growth (host-side validation scratch directory only): 6.2 MB for 19 real stored images.
  **The real, deployed `content_worker` container's own `/data/image_storage` volume remains at
  4.0 KB (empty)** — confirmed directly — since every validation write targeted a local,
  disclosed, host-side path, never the production volume.
- Worker stability: `content_worker` was not restarted or reconfigured for Phases A/B; it continued
  its own normal, independent `CONTENT_GENERATION` cadence throughout, unaffected. No slowdown,
  error, or crash attributable to this validation was observed in its logs.
- **Confirmed zero LLM/provider calls**: `run_shadow_discovery()`'s own module graph contains no
  `openai`/`integrations.llm_gateway` import (the exact AST-based test from the M1-M6 test suites,
  re-run in §15) — the only network calls this validation made were the same bounded, unauthenticated
  HTTP(S) fetches (`integrations/http/safe_fetch.py`) M2-M4 already validated as safe.

## 13. Known issues

1. **Google News RSS aggregator image miscalibration (the headline finding, §10)** — **29% of the
   full 100-event sample** (precisely measured directly against the persisted data, not estimated).
   Root cause: a Google News RSS item's own `<link>` resolves to a Google-hosted redirect page whose
   `og:image` is Google News' own generic app icon, not the publisher's real article image — M2's
   article-metadata fetch is working exactly as designed, but the *input URL itself* is not the
   publisher's real page for this specific source pattern.
2. **GitHub-release-card genericness** — a repo's social-preview card is identical across every
   release/tag of that repo (2+ instances observed directly). Correct project identification, zero
   release-specific differentiation — a real but much lower-severity finding than #1 (still the
   correct organization/project, unlike #1's fully-unrelated generic icon).
3. **Telegram source coverage is unproven at this sample size** — 0/2 Telegram-sourced events in
   the 100-event sample produced any candidate; n=2 is too small to generalize a real gap from a
   sampling artifact. Needs a larger, Telegram-weighted follow-up sample before drawing a
   conclusion either way.
4. **No cross-event duplicate detection** — carried over, disclosed limitation from M3 (dedup is
   scoped per-event only) — directly responsible for why 12 near-identical Google-News-icon
   instances were never merged into one cluster; each event's own M3 pass correctly found *no*
   duplicate *within that single event*, since no other candidate for that same event existed to
   compare against.
5. **A latent FK-driven test fragility, discovered and fixed during this validation**: linking real
   `image_candidates` rows to a real, pre-existing `content_drafts` row (§11's live-send test) broke
   two unrelated tests (`tests/test_editorial_inbox_service.py::test_empty_result_returns_empty_
   list`, `tests/test_news_handler.py::test_integrated_stack_empty_state`) that each perform a blunt
   `DELETE FROM content_drafts` as their own setup - the new `image_candidates_content_draft_id_
   fkey` (added in M6) now prevents that delete while any row still references it. This is a real,
   general risk M6's own schema introduced (not previously exercisable, since M6/M7 had never
   before linked a real candidate to a real draft) - **any future production use of `link_
   candidates_to_content_draft()` against a draft some other blunt cleanup routine expects to
   freely delete will hit the same conflict.** Fixed for this validation by nulling the three
   affected rows' `content_draft_id` back to `NULL` (the underlying audit rows, and everything this
   report claims about them, are unaffected - the FK link was verified working, then removed
   again). Flagged here as a real, disclosed, actionable finding for Phase 17, not swept under the
   validation-only scope of this milestone.
6. **`tests/test_triage_orchestrator_cycle.py` is not isolated from real, concurrently-arriving
   collector activity** - discovered incidentally during this milestone's own regression-suite runs
   (unrelated to Image Intelligence): `run_triage_cycle()` scans and claims *every* real eligible
   `NewsEvent` system-wide, not just a test's own created row, so a long-running full-suite pass
   during which this project's own always-on collector/analysis workers keep adding real rows
   non-deterministically inflates assertions like `events_recovered == 1`. Confirmed by observing
   two *different* tests in that same file fail on two separate full-suite runs during this
   session, each with a different real, non-1 count - not a Phase 16 regression (no code this
   milestone touched is anywhere on that call path), but a real, pre-existing test-isolation gap
   worth flagging for whoever next touches that file.

## 14. Activation recommendation

**Option B: NEEDS CALIBRATION.**

**What works** (validated with real data, not projected): secure fetch, technical validation,
quality gating, per-event deduplication, relevance ranking, persistence (audit rows + real byte
storage + retention schema), and the Telegram preview send/link path — all performed correctly,
deterministically, and with zero LLM cost across a real, naturally-collected, 100-event sample.
Coverage (89-92% for RSS/NEWS_API), quality-score distribution (79% of candidates ≥70/100), and
dedup accuracy (12.4% correctly caught, zero observed false-positive/negative in visual spot-check)
are all healthy, activation-ready numbers on their own.

**What needs calibration before a live flip**: the Google News aggregator-image pattern (§10/§13
item 1) is a real, material, likely-recurring failure mode for any Google-News-RSS-sourced event —
35 of the 100 sampled events were `news.google.com` links (a substantial subset of the 85 RSS
events), and **29 of those 100 events (29% of the entire sample) got the single identical generic
Google icon as their top-ranked, editorial-eligible candidate** — precisely measured, not
estimated. Recommended minimal, targeted fix before enabling `image_editorial_preview_enabled` in
production: either (a) have M2's own article-fetch step follow the Google News redirect to the
*actual* publisher URL before extracting metadata (the most structurally correct fix, but a real
code change - out of scope for this validation-only milestone), or (b) add Google's own
news.google.com host to a low-priority/deprioritized provenance bucket in `services/
image_relevance.py`'s existing `PROVENANCE_TABLE` so a same-domain "match" against a Google
redirect page scores low enough to fall back to `INSUFFICIENT_EVIDENCE` rather than a false
`RANKED` top candidate (a smaller, more contained change). **Neither fix was made in this
milestone** (M7 is validation, not development, and neither is a "critical validation blocker" in
the sense of stopping the validation itself from completing).

## 15. Testing

- `python -m ruff check .` (full repository, including the new `scripts/phase16_m7_shadow_
  validation.py`): all checks passed.
- `-k image` selection (M1-M6 image-intelligence test files, including all M6 Telegram-preview,
  persistence, and retention tests): **416 passed**, 0 failed, 0 new regressions.
- Full repository suite (`python -m pytest -q`), first pass: 18 failed — the exact 15-failure
  pre-existing baseline the M3/M4/M5/M6 reports already documented, **plus 2 genuinely new
  failures directly caused by this milestone's own §11 live-send test** (the FK conflict, §13 item
  5) **plus 1 pre-existing, unrelated triage-orchestrator flake** (§13 item 6, confirmed
  non-deterministic and unrelated to Image Intelligence on a dedicated re-run). The 2 FK-caused
  failures were root-caused and fixed (§13 item 5).
- Full repository suite, **final authoritative pass after the fix: 1663 passed, 15 failed** — back
  to exactly the same 15 pre-existing baseline test names as every prior Phase 16 report, in the
  same files (`test_capability_executor.py` ×8, `test_content_generation_integration.py` ×1,
  `test_content_worker_cycle.py` ×2, `test_editorial_scoring.py` ×2, `test_fact_safety.py` ×2).
  Neither the FK failures nor the triage flake reappeared. **Zero new regressions from this
  milestone's validation work.**
- Migrations: unchanged (`31a8d7c95c87`, head) — M7 added zero schema.
- Containers: all five (`backend`/`automation_worker`/`content_worker`/`news_analysis_worker`/
  `postgres`/`redis`) healthy throughout, `content_worker` never restarted or reconfigured.

## 16. Phase 17 handoff notes

- The Google News aggregator-image finding (§13/§14) is the single most actionable item for
  whatever comes next — a targeted fix (redirect-following or provenance deprioritization) is small,
  bounded, and would directly close this milestone's one material gap before any live flip.
  `scripts/phase16_m7_shadow_validation.py` remains in the repo (kept per this codebase's own
  established validation/backtest-script precedent) and can be re-run against a larger or
  differently-sampled window to re-measure after such a fix.
- `image_candidates` now holds 288 real rows from this validation (legitimate, non-synthetic real
  data — the exact kind of evidence shadow mode exists to produce) — a genuine, small head start on
  whatever the next real shadow-collection window needs.
- The Telegram-source-coverage question (§13 item 3) needs a larger, Telegram-weighted sample
  before any conclusion — worth a follow-up pass specifically targeting Telegram-sourced events if
  Telegram coverage matters for the next phase's own goals.
- `IMAGE_INTELLIGENCE_MODE`, `IMAGE_CANDIDATE_PERSISTENCE_MODE`, and
  `IMAGE_EDITORIAL_PREVIEW_ENABLED` all remain `off`/`off`/`False` in `.env` and in every deployed
  container — this milestone changed no production posture, per its own explicit safety rules.

## Rollback

Nothing to roll back — no code, schema, or `.env` change was made in this milestone; the only
durable artifact is the 288 real, legitimate `image_candidates` rows this validation generated
(§16), which are additive and harmless to leave in place, matching the existing M5 retention
schedule (they will age out naturally per `image_metadata_retention_days`/
`image_finalist_metadata_retention_days` if never explicitly cleared sooner). The one exception:
the three rows' `content_draft_id` linkage created by §11's live-send test was deliberately
reverted to `NULL` (§13 item 5) once it was confirmed working, to remove the FK conflict it caused
for two unrelated tests - the underlying audit rows themselves were left in place.

## M7 verdict

**PHASE 16 M7 COMPLETE — IMAGE INTELLIGENCE VALIDATED (NEEDS CALIBRATION BEFORE ACTIVATION)**
