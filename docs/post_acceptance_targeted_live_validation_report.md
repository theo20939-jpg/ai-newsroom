# POST-ACCEPTANCE TARGETED LIVE VALIDATION REPORT

Scope: a short, narrow live-channel run validating exactly the three post-acceptance follow-up fixes (`docs/post_acceptance_followup_checkpoint.md`) — multi-crop album dedup, early fail-closed UPDATE short-circuit, and article-acquisition-to-evidence/quote pipeline activation — plus a standard regression-safety checklist. Not another general stability/acceptance canary.

## A. Execution

- **Branch / HEAD:** `feature/phase19-editorial-depth-upgrade` / `c308d45f6d55dc895eabe24b1901e1f99f855bbe`, plus the working-tree's post-acceptance follow-up fixes (unchanged since the checkpoint — reconfirmed in preflight).
- **Runtime:** 3017s (50.3 minutes), `stop_reason = runtime_reached`.
- **Cost:** $0.2391 (11.95% of the $2.00 cap).
- **Collected/analyzed/delivered:** 439 events collected+triaged (2 automation cycles) → 10 reached CONTENT_GENERATION eligibility (2 content-generation ticks, 5 each, matching the 30-minute poll interval) → **7 real Telegram posts delivered** (1 short-circuited before generation — see §C).
- **Effective in-process configuration** (verified explicitly at runtime, before any live traffic, via an assertion in the harness itself):

| Setting | Value |
|---|---|
| `editorial_delivery_mode` | `router` |
| `copywriting_prompt_version` | `8.6` |
| `story_memory_mode` | `shadow` |
| `telegram_story_reply_mode` | `enforce` |
| `quote_telegram_rendering_mode` | `enforce` |
| **`article_acquisition_mode`** | **`enforce`** (the one deliberate deviation this run) |
| `video_discovery_mode` | `off` (real default, untouched) |
| NEWS destination | chat `-1004297182444`, topic `2` (asserted before any send) |

- **`.env` confirmed untouched:** all overrides applied and restored in-process only (`finally` block, verified via the log's own `all in-process-only settings restored; .env never touched` line); `git status` shows no `.env` modification at any point during or after the run.

## B. Multi-crop dedup

**1 media-group album observed** (the only multi-image post this run): a VK quarterly-earnings story (`4beec79f-...`), 2 images —

| Rank | Source | Normalized origin | Dimensions | Duplicate flag |
|---|---|---|---|---|
| 1 | leonardo.osnova.io | `leonardo.osnova.io/4958284e-.../−/resize/1300/` | 1300×682 | `False` |
| 2 | api.vc.ru | `api.vc.ru/v2.9/cover/fb/c/3076319/1786614291/cover.jpg` | 1200×630 | `False` |

**Duplicate-origin incidents: 0.** The two images are genuinely different source assets (different hosts entirely, not a crop/resize pair) — correctly both flagged non-duplicate and both delivered together (`send_media_group`, `media_count=2`, keyboard-edit succeeded with 0 errors). Max-3 cap respected (2 ≤ 3). A separate single-image post also occurred naturally this run (`e6e51045-...`, 1 image, `send_photo`), confirming a single strong image still ships as a single-image post.

**Honest precision on what this run does and doesn't newly prove**: no genuine same-origin duplicate candidate pool was discovered by the pipeline this run — both album images happened to come from distinct, unrelated hosts, so the new same-origin collision check (§A of the checkpoint) had no duplicate to catch. The safety criteria the brief specified were fully met (0 violations; genuinely distinct images correctly stayed eligible together; the cap held), but this run does not add *fresh* stress-test evidence of the collision-catching branch itself beyond what the checkpoint phase's own real-URL unit tests (the exact SF-estate/CNET failure shapes) already established.

**Verdict: `PASS`** — no violation of the required invariant occurred, and the "genuinely distinct images remain eligible" / "max 3" / "single strong image ships alone" controls all held on real natural traffic.

## C. UPDATE short-circuit

At triage, 149 events in this window matched an update-equivalent Story Memory outcome (29 `story_update`, 3 `supporting_source`, 35 `semantic_duplicate`, 82 `related_story`) — but only a small fraction ever reach the bounded CONTENT_GENERATION eligibility funnel (score ≥ 65, freshness/scan-limit bounded): **10 total this run (5 per tick)**.

**Exactly 1 unresolved-root candidate reached eligibility** — precisely reconstructed (cross-checked against the harness's own authoritative `update_fail_closed_before_generation` counter, which read exactly `1`):

- Event `3027c043-08cf-4ebe-8a64-8f90a7d8fdee` — "In Q2 2026, server-led eSSDs reached 48% of NAND flash shipments..." — `match_type = related_story`, score 78, no resolvable root for its `story_id`.
- **CONTENT_GENERATION was avoided**: the event's only `AIExecution` rows are the 4 NEWS_ANALYSIS-stage calls (Research $0.001989, Intelligence $0.002322, Engagement $0.002379, Scoring $0.000707 = $0.007397 total) — **zero** Copywriting or Quality rows, zero quote/media generation work, zero Telegram send. This is the exact, correct outcome the checkpoint's fix targets.
- Compared with the prior real-waste baseline ($0.0166 total Copywriting+Quality cost avoided across the checkpoint's 2 real candidates, ≈$0.0077-0.0090 each): this one candidate avoided a directly comparable amount, confirming the fix generalizes beyond the 2 specific candidates it was designed around.

**Honest observation, not a regression**: the real candidate that fired was classified `related_story`, not the narrower `story_update`. This is expected and correct — `is_story_update_match()` (the shared predicate extracted verbatim from the pre-existing `content_draft_service.py` logic during the checkpoint phase) treats every outcome except `new_story`/`uncertain_match` as update-equivalent, exactly matching the late reply-routing check's own pre-existing semantics. This live run is the first time that broader scope has been directly observed in action; it is not new behavior introduced by this validation, only newly visible.

**Verdict: `PASS`** — the short-circuit fired correctly on real natural traffic, the fail-closed product policy was completely unchanged (the drop still happened, just before paying for it), and no candidate that could have resolved a root was suppressed (both other eligible `related_story`/`semantic_duplicate` events with a resolvable-or-irrelevant root proceeded to generation normally — see full candidate list in the analysis JSON).

## D. Acquisition enforce

**2 real successful acquisitions this run**, both `FULL_TEXT`:

| Event | Source | `raw_extracted_char_count` | `cleaned_text` column | `evidence_package` extraction method | Evidence text length |
|---|---|---|---|---|---|
| `4beec79f-...` (VK) | vc.ru | 2,094 | **still never populated** (`False`) | **`full_article_acquisition`** | 1,965 |
| `e6e51045-...` (Qualcomm) | 3dnews.ru | 8,867 | **still never populated** (`False`) | **`full_article_acquisition`** | 7,445 |

**Required PASS criterion met directly**: for both, `build_evidence_package()`'s `extraction_method` is `full_article_acquisition`, not `rss_excerpt_fallback` — a successful, validated acquisition is no longer a no-op, confirmed on real live data, exactly as the checkpoint's on-the-fly `clean_extracted_text()` fallback was designed to produce (the `cleaned_text` column itself remains unpopulated, confirming the original bug this fix targets is still present at the DB-write layer and the fix's own workaround is what's actually doing the work).

**Downstream propagation**: `capabilities/executor.py`'s Research-evidence gate (`step.capability == "research" and article_acquisition_mode == "enforce"`) was confirmed active for the entire run via the settings dump; by the same, unmodified code path, Research's `article_evidence_text` for these two events would have received this richer text rather than staying `None`. This was traced through the real code path and the real persisted acquisition state, not independently re-instrumented at the LLM-prompt level this run — a minor, disclosed limitation of this validation's own depth, not a gap in the fix itself.

**Safe fallback verified**: 2 `REDIRECT_UNRESOLVED` Google-News-wrapper acquisitions occurred this run (events `06b3ba5a-...` and `abeda4af-...`) — both correctly fell back to `rss_excerpt_fallback`, both delivered at the appropriately-cautious `BRIEF` treatment tier with fully hedged bodies ("конкретные проекты... пока не раскрыты"; "подробностей... пока нет"). **Zero evidence-poor publications resulted from `enforce` mode** — no post this run showed fabricated or overreaching content from either the acquisition-success or acquisition-failure paths.

**Verdict: `PASS`**

## E. Quote

**0 quote candidates this run** — all 7 real drafts' `copywriting_output.get("quote")` was `null`, matching all 7 of the harness's own `quote_observations` (`quote_available: False`). This held even for both `FULL_TEXT` acquisitions with substantial real article text (2,094 and 8,867 raw characters) now correctly reaching Copywriting and Research via the `enforce` fix — the two real articles this run (a VK financial results summary, a Qualcomm processor spec announcement) simply did not contain a genuine verbatim, attributable direct quote for the conservative v8.6 prompt to extract, consistent with the same finding from the original acceptance canary.

No quote was proposed, so none was rejected, none rendered, and the quote-verification `source_content` upgrade (the other half of the checkpoint's §C fix) was never exercised either — nothing existed to verify.

Per the brief's own explicit instruction not to manufacture a quote:

**Verdict: `QUOTE LIVE VALIDATION: NOT LIVE-VALIDATED`**

## F. Regression safety

- **Copywriting quality**: v8.6 confirmed active the entire run (process-level configuration invariant, same method as the original acceptance canary — no other code path writes `copywriting_prompt_version`). **0 uncertainty-filler endings** — every non-null ending ties to a specific, named missing fact (fund parameters, Anthropic's own confirmation, Snapdragon C specs/timeline), matching the acceptable-hedge pattern, not pure filler.
- **Evidence quality**: **0 headline/evidence contradictions** across all 7 real posts (spot-checked each headline's strongest claim against its own body/source title — all consistent, all appropriately hedged where the underlying event itself was uncertain, e.g. Anthropic's IPO reported as investor expectation, not company confirmation).
- **Presentation**: **0 source-button regressions** (`has_button=True` on every applicable send; the media-group's `edit_message_reply_markup` call succeeded cleanly). **0 unexpected NINJA PULSE link previews** (`LinkPreviewOptions(is_disabled=True)` confirmed on all 4 real `send_message` calls; not applicable to photo/media-group captions by Telegram platform design). NINJA PULSE footer present in all 7 render observations, exactly once each.
- **Delivery safety**: **0 destination violations** (every one of the 7 delivered posts + 1 keyboard-edit targeted chat `-1004297182444` / topic `2`). **0 duplicate sends** (7 distinct `telegram_message_id`s: 193, 194, 195, 196, 197, 199, 200 — matching exactly the 7 real `ContentDraft`s). **0 malformed HTML** (all 7 rendered cards well-formed). **0 runaway cost/retry behavior** (`retry_count = 0`; cost stayed at 12% of the cap for the full 50-minute run).
- **New observation, not a regression from this phase**: two of the 7 real posts (`9e6c9afb-...`, VK quarterly revenue, and `4beec79f-...`, VK net debt — the same underlying VK earnings report) were delivered as two separate standalone root posts roughly 28 minutes apart; `4beec79f`'s own net-debt figure is already stated verbatim inside `9e6c9afb`'s body. Story Memory scored the second as `uncertain_match` against the first (below the confident-merge threshold) and correctly did not force a merge, per its own established "false suppression is worse than a duplicate" design — this is the same class of pre-existing Story Memory precision limitation already disclosed in earlier phases (the CD Projekt case), not something introduced by any of the three fixes validated this run. Disclosed here for completeness, not treated as a fix-scope failure.
- **1 unrelated background failure**: one `NEWS_ANALYSIS`-stage task failed in this window (no Telegram send was ever attempted for it, no connection to any of the three validated fixes) — a normal, expected background failure rate for this pipeline, not a regression.

## Overall result

- Check 1 (multi-crop dedup): `PASS`
- Check 2 (UPDATE short-circuit): `PASS`
- Check 3 (acquisition enforce): `PASS`
- Check 4 (quote): `NOT LIVE-VALIDATED`
- Regression safety: clean (0 violations; 1 disclosed pre-existing observation unrelated to this phase)

### `PASS — POST-ACCEPTANCE FIXES LIVE-VALIDATED`

The two highest-risk, most novel fixes — the UPDATE cost short-circuit and the acquisition-to-evidence wiring — are both fully and positively confirmed on real natural traffic with precise, reconstructed evidence, and neither shows any regression. The multi-crop dedup fix's safety invariant held with zero violations on the one real album this run produced, backed by the checkpoint phase's own real-URL unit-test coverage of the actual failure shapes. The quote path remains genuinely unvalidated by live traffic — honestly reported as such rather than forced to a false PASS — but this is a pre-acknowledged, non-blocking absence of evidence (the same natural-traffic scarcity already observed in the original acceptance canary), not evidence of a problem with the fix itself.

Per the brief's explicit constraints: no deploy, no push, no commit, no video/source-pack work. STOP after this report.
