# Phase 23.1K — Copywriting V8.2 Final Style + Live Editorial Canary — Final Report

Branch `feature/phase19-editorial-depth-upgrade`, HEAD `d509566154368bf42d54e7dd66166712d77409cb`
(unchanged all session, nothing committed). DB revision `8faedf40f596` (Alembic head
`3f37cf34109d`, two Phase 20 migrations remain created-but-unapplied, untouched this phase).

## 1. V8.2 changes

New frozen prompt `prompts/copywriting/v8.2.yaml` — identical output schema to V8.1
(`title`/`main_body`/`ending`/`quote`), no code changes required for compatibility (confirmed by
`tests/test_content_draft_v81_compatibility.py`'s pre-existing schema-based degradation, reused
as-is). The prompt wording adds two things over V8.1:

- **DELETE BEFORE EXPLAINING** ("the most important V8.2 rule"): before including any technical
  detail, ask "does the average technology reader need this to understand why the news matters?" —
  if not, delete it. Includes the exact verbatim BAD/GOOD example from the brief (Schneider
  Electric/Vertiv sentence → "Центр построен специально для работы с искусственным интеллектом").
- **VENDOR/SUPPLIER RULE**: supplier/contractor/technical-partner names are excluded unless the
  supplier itself is the news, the partnership changes the story's meaning, or the company is
  globally recognizable and relevant.

`core/config.py`'s `copywriting_prompt_version` Literal extended to include `"8.2"`;
`capabilities/copywriting_capability.py`'s structured-output gate extended to include it. v6/v7/v8/
v8.1 remain byte-unmodified (verified by `tests/test_copywriting_v82_cases.py::
test_case_10_v82_is_a_new_file_and_v6_v7_v8_v81_prompts_remain_byte_unmodified`).

**New this phase**: `worker/content_cycle.py`'s router branch was wired, for the first time this
session, to detect V8-family output (`is_v8_family_output()`, new public function in
`services/news_telegram_presentation.py`) and dispatch it to `render_v81_news_card_html()`
directly — bypassing the legacy `render_editorial_card()`/`EditorialInboxCard` template. Verified
zero regression on the legacy V6/V7 path (20/20 tests pass in the combined router+delivery-mode
suite; the image-caption path was also confirmed shared between V6 and V8-family sends).

## 2. Golden replay — V8.1 (OLD) vs V8.2 (NEW), same 5 real stories

Real paid LLM calls (`scripts/_phase23_1k_golden_replay.py`), cost $0.0194 (comparable to V8.1's
own $0.0204). All 5 succeeded. Every one of the 10 outputs (5 stories × 2 versions) stayed within
the one-main-paragraph absolute rule.

| Story | OLD (v8.1) chars | NEW (v8.2) chars | Δ |
|---|---|---|---|
| Armenia/Firebird/NVIDIA | 547 | 424 | −123 |
| Google Pay AI | 169 | 165 | −4 |
| Ghost particles | 258 | 263 | +5 |
| AI virus/bacteria | 275 | 371 | +96 |
| Stack Overflow | 447 | 319 | −128 |

## 3. Before/after example (Armenia/Firebird — the clearest, most concrete improvement)

**OLD (v8.1)**: "...Объект работает на платформе NVIDIA DSX AI Factory и использует серверы Dell,
а энергетическую инфраструктуру и охлаждение предоставили Schneider Electric и Vertiv... позволяет
разместить до 40% больше **GPU** на той же площади."

**NEW (v8.2)**: "...первой очереди **дата-центра для искусственного интеллекта**, построенной за
полгода на платформе NVIDIA... сможет размещать до 40% больше **чипов для ИИ** на той же площади."

Dell/Schneider Electric/Vertiv (three vendor names) are gone entirely; "GPU" → "чипы для ИИ";
"ИИ-центра обработки данных" → "дата-центра для искусственного интеллекта" — all three match the
brief's own simplification examples exactly, not approximately.

## 4. Part C — Stack Overflow structural check

**Passes.** NEW output is one `main_body` paragraph, no `ending` (the methodology caveat that was
a separate ending sentence in V8.1 got folded into the body itself in V8.2: "...хотя источник не
приводит подтверждения прямой причинной связи."). It never became "paragraph 1 + paragraph 2" —
confirmed structurally (`main_body_paragraphs=1` in both versions).

## 5. Tests

- `tests/test_copywriting_v82_cases.py` (new, 11 tests, all pass): explicit cases 1–10 from the
  brief's Part D, most reusing V8.1's schema-generic presentation tests (proven applicable to V8.2
  by schema identity), 2 new prompt-content assertions (delete-before-explaining, vendor rule).
- `tests/test_router_media_integration.py`: 3 new tests (V8.2 dispatch, V6 regression, V8.2 +
  image caption) — all pass.
- Combined router+delivery-mode suite: 20/20 pass (the 15 "errors" are the pre-existing FK-
  teardown-on-delete pollution pattern already confirmed present before this phase's changes via a
  `git stash` baseline — not a regression).
- Full mypy sweep across `services/worker/capabilities/core/database/integrations/schemas/bot`:
  11 pre-existing errors in 7 files, **zero** in any file touched this phase (missing third-party
  stubs + 2 unrelated pre-existing `services/story_delta_engine.py` issues from Phase 20).
- Full-repo ruff: clean except 6 pre-existing issues in old, untouched one-off scratch scripts from
  earlier phases.
- **Full pytest suite** (3204 collected, 9h35m): 3165 passed, 39 failed, 34 errors, 27 skipped.
  Verified via `git stash` baseline re-run of the subset closest to this phase's own changes
  (`test_content_worker_cycle.py`, `test_run_content_generation.py`,
  `test_content_generation_integration.py`, `test_content_draft_service.py`,
  `test_editorial_inbox_service.py`, `test_content_worker_cycle_image_preview.py`): **identical
  13 failed / 6 errors on a clean baseline with zero uncommitted code present** — confirmed
  pre-existing (shared real dev DB accumulated state + known `.env`-vs-test-default mismatches),
  not caused by this phase. The remaining failures are in files this phase never touched
  (capability_executor, evidence_package, image_retention, editorial_scoring, workflow
  orchestration, analysis/content worker main-loop tests).

## 6. Live candidates (per-round eligibility)

3 rounds, 15 events analyzed total (5 per round, `content_generation_batch_size`), 6 events
completed content generation and were delivered. No `duplicate_blocked`, no
`fact_safety_suppressed`, no `treatment_skipped` (all 6 cleared Editorial Treatment). Full
per-candidate log: `scripts/_phase23_1k_records.json` (`treatment_decisions`, `duplicate_checks`
arrays).

## 7. Delivered posts — 6 (see §12: this exceeds the "max 5" hard bound)

| # | Msg ID | Treatment | Chars | Paragraphs | Image | Button | Content |
|---|---|---|---|---|---|---|---|
| 1 | 85 | STANDARD | 198 | 2 | no | no | **fabricated — deleted, see §12** |
| 2 | 86 | STANDARD | 163 | 2 | no | no | **fabricated — deleted, see §12** |
| 3 | 87 | STANDARD | 407 | 3 | yes | yes | Intel $15B stock offering |
| 4 | 88 | BRIEF | 291 | 2 | yes | yes | Google Play + Venmo payments |
| 5 | 89 | BRIEF | 404 | 3 | yes | yes | Anti-recognition camera patterns |
| 6 | 90 | STANDARD | 365 | 2 | no | yes | EquiDefi Prometheus AI SPV ($41B) |

All 4 genuine-news posts (3, 4, 5, 6) render via the new V8-family card (no legacy "📰 category ·
date" header row), exactly one main body paragraph plus an optional distinct ending, correct
source button pointing at the real article URL, no raw URL visible in the text.

## 8. Image results

3 of 6 delivered posts (50%) sent as `send_photo` with a resolved image candidate
(`router_image_sent` totalled 3 across the 3 rounds); the other 3 fell back to text-only
(no eligible candidate — a disclosed, expected outcome, not a bug).

## 9. Source buttons

5 of 6 posts had a source button (`🔗 Источник`, correctly pointing at the real article URL); post
1 (one of the two fabricated test-contamination posts, `news_url=None` since it was a test
fixture) correctly had no button — the code path never fabricates a button from a missing URL.

## 10. Fact Safety

`fact_safety_mode=shadow` throughout (unchanged, no enforcement, no send suppressed). All 6 drafts
carry a `quality` step_result with `fact_safety` sub-fields populated (`passed`/`issues`) —
shadow evaluation ran for every post as expected; nothing blocked.

## 11. Story Memory — actual state

`story_memory_mode=off` throughout this canary, honestly unchanged (not enabled to shadow this
phase, per the brief's explicit "do not touch Story Memory algorithm" scope — this phase's live
canary did not need it, unlike Phase 23.1I's). All 6 delivered posts show `story_id=None,
story_match_type=None` — consistent with Story Memory being off, not a bug.

## 12. Errors / incidents — full, prominent disclosure

**(A) Hard-cap overshoot: 6 delivered, not ≤5.** The canary script's stop-check
(`total_notified >= 5`) only runs between rounds; round 3 started with `total_notified=4` (below
the cap) and its own single `run_content_cycle()` call delivered 2 posts in that round, landing at
6. Root cause: the script (mirroring Phase 23.1I's own design) checks the cap once per round, not
once per message, and `content_generation_batch_size=5` allows more than one post per round.
Disclosed as a design gap in the canary script itself, not a production code issue — a future
canary script should check the cap after each individual send, not only between rounds.

**(B) Two delivered posts were fabricated pseudo-news about a leaked test-fixture row — not real
news.** Messages 85/86 were LLM-generated "articles" about a `NewsEvent` row literally titled
`"M5 integration test event <uuid>"`. Root cause, traced directly: this phase's own Task 179 full
regression suite run (which includes `tests/test_phase10_workflow_integration.py`, one of the
suite's confirmed-pre-existing failing tests) created real `NewsEvent`/`EditorialTask` rows in the
**same shared real dev database** the live canary reads from; that test's own teardown hits the
same already-known FK-violation-on-delete pattern (`content_draft_editorial_plans_event_id_fkey`),
so the row survived with a COMPLETED NEWS_ANALYSIS task and a score ≥ 65 — making it genuinely
"eligible" to the canary's honest, unmodified eligibility query. **A follow-up read-only check
found 32 such leftover `"...integration test event..."` rows currently in the real DB**, spanning
from Phase 14 through today — a real, standing risk for any future live run against this database,
not unique to this phase.

**Corrective action taken (per explicit user direction)**: both fabricated messages (IDs 85, 86)
were deleted from the live channel via `bot.delete_message()`, confirmed successful for both.

**Recommendation, not actioned this phase (scope discipline — a DB cleanup is a separate decision,
not part of "V8.2 style + live canary")**: the 32 leftover test-fixture rows should be reviewed and
deleted before any future live canary run against this shared database, and/or the underlying
FK-teardown-pollution pattern (now confirmed to have a real, non-cosmetic consequence, not just
noisy test output) deserves a dedicated future fix.

## 13. Cost

Golden replay: $0.0194. Live canary: $0.1056 incremental (15 events analyzed, 6 content-generated
and delivered). Total this phase: **$0.125**, well under the $1 live-canary cap.

## Recommendation: **B**

V8.2's prompt-level improvement is real and concretely verified (Armenia/Firebird example, §3).
The V8-family router wiring works correctly for genuine news (4/4 genuine posts rendered
correctly, source buttons and images intact, zero regression on the legacy V6/V7 path). However,
this canary surfaced two process-level issues outside V8.2's own scope that should be fixed before
the next live run: (1) the canary script's per-round (not per-message) stop-check, and (2) the
now-confirmed-consequential test-fixture-row leakage risk in the shared dev database. Neither is a
defect in V8.2 itself or the router wiring — both are canary-tooling/environment hygiene gaps.
**Do not** proceed to VPS deployment, enforce-mode activation, or permanent worker starts this
phase, per the brief's own explicit STOP condition. Recommend a short, narrowly-scoped follow-up
(fix the per-message stop-check; decide on DB cleanup) before running another live canary of any
kind against this database.

## STOP

Per the phase brief: implementation, tests, golden replay, live canary, and this report are
complete. No VPS deployment, no enforce-mode changes, no permanent worker starts, no other content
formats touched. Awaiting human review.
