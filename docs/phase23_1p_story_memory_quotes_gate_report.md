# Phase 23.1P — Story Memory / Quotes / Editorial Gate — Final Report

Branch `feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(unchanged, nothing committed). Real Postgres/Redis only; no application worker containers were
ever started this phase; real paid LLM calls; real Telegram sends to the one approved destination.

## Executive summary

Closed three real, evidence-based gaps from Phase 23.1O. **Story Memory** now genuinely runs
(`story_memory_mode=shadow`, in-process, restored to `off` on exit) with its already-built V2
delta/confidence/suppression layer wired in for real diagnostics and a more precise delivery-time
guard — but empirically does **not** retroactively fix either named 23.1O regression (Zoom,
Supermassive), a disclosed architectural recall limit, not a wiring gap. **Quotes** now reach
Copywriting from the real acquired article text instead of a thin RSS stub — proven live (a real,
verified quote was extracted for the first time ever in this project's history) — but the live
canary surfaced a **second, previously-invisible gap**: the active V8.5 renderer never incorporates
the `quote` field into the delivered card at all, so the fix's own success was not visible in the
final Telegram output. **The Terraria editorial-gate regression is fixed** and verified live (no
recurrence of that exact bug), but the same canary surfaced a **different**, real gate-timing race
(article acquisition completing moments after the treatment check already ran). Given two new,
real, disclosed gaps were found by the very testing this phase itself designed, the honest
recommendation is **B — small fix required**, not A.

## 1. Why Story Memory was OFF in Phase 23.1O

`services/triage_orchestrator.py`'s own gate: `if settings.story_memory_mode != "off": await
_apply_story_memory(...)`. `.env` simply never sets `story_memory_mode`, so the code default
(`"off"`) applies — the same deliberate default since Phase 18.10, never flipped in this project's
history before this phase. Not a bug; a conservative default nobody had yet turned on for a real
canary.

## 2. What changed

Three narrow, evidence-based changes, all confirmed via direct code reading before implementation
(`docs/phase23_1p_story_memory_quotes_gate_report.md`'s own forensics, §A1–C1 of the working
notes):
- **Story Memory**: `triage_orchestrator.py::_apply_story_memory()` now additionally computes and
  LOGS (never persists — no migration applied) Story Memory V2 diagnostics
  (`services/story_delta_engine.py` + `story_confidence.py` + `story_suppression.py` — all
  pre-existing, fully built, never wired in before this phase) for every confident match.
  `services/story_duplicate_guard.py::check_duplicate_story_delivery()` now uses the V2-aware
  `compute_would_suppress()` (strictly more conservative than the old match-type-only check) as
  its real block decision.
- **Quotes**: `capabilities/executor.py` now populates a new `BusinessContext.quote_source_text`
  field (from the already-acquired `NewsEventArticleAcquisition.raw_extracted_text`, cleaned via
  the already-existing `services/article_cleaning.py::clean_extracted_text()`) for the
  "copywriting" step only, when `article_acquisition_mode != "off"`. `capabilities/
  copywriting_capability.py::_format_quote_source_excerpt()` now prefers it over the old,
  frequently-thin `news_event.content`. `_QUOTE_SOURCE_EXCERPT_CHARS` raised 3000→6000 with direct
  measured evidence (a real useful quote measured at character offset 3364, past the old cap).
- **Editorial gate**: `services/editorial_treatment.py::_is_weak_evidence()` no longer treats
  `FETCH_FAILED` as unconditionally "not weak" — a new `_fetch_failed_content_is_thin()` check
  (self-relative: is `news_event.content` no longer than its own title) closes the exact gap that
  let the real Terraria story slip past the SKIP gate.

## 3. Whether Story Memory genuinely ran in the final canary

**Yes, confirmed directly from the real database**: 147 `NewsEventStoryLink` rows were created
during the canary window (`2026-08-11T18:17:23`–`19:54:04 UTC`), a real, diverse distribution
across every outcome Story Memory defines.

## 4. Number of Story Memory consultations

**147** — every triaged event during the window was matched against the real candidate pool.

## 5. NEW count

**96** (`new_story`).

## 6. DUPLICATE count

**6** (`semantic_duplicate`).

## 7. SUPPORTING_SOURCE count

**1** (`supporting_source`).

## 8. UPDATE count

**1** (`story_update`).

## 9. UNRELATED / other count

**36** `related_story` (this codebase's own closest analogue to "unrelated but same entity
family" — see Phase 20's own design) + **7** `uncertain_match` (genuinely ambiguous, never
auto-classified either way).

## 10. Number of duplicate deliveries prevented

**0.** None of the 6 `semantic_duplicate`/1 `supporting_source` matches had a prior ROOT delivery
at the moment they were classified (`prior_root_delivery_existed_at_check_time: false` for every
one, confirmed directly) — meaning no actual blocking OPPORTUNITY arose this run. Story Memory
correctly *classified* real duplicates (e.g. a real "Artificial Intelligence Resolves 5,000-Year-
Old Mystery in Female Sexology" story syndicated across 3 different local-news outlets, and an
identically-titled item collected via two different feeds one second apart) — but the guard's
*blocking* behavior was not exercised live this run, only its classification accuracy.

## 11. Number of duplicate deliveries that still escaped

**1, disclosed.** Post #6 (Brad Lightcap leaving OpenAI, TechCrunch, 18:53:45) is very plausibly
the same real event as Post #1 (Brad Lightcap leaving OpenAI, Techmeme, 18:25:52, 28 minutes
earlier) — both describe him leaving to "start something new." Story Memory linked Post #6 to
`related_story` against a *different* prior story, never comparing it directly to Post #1's own
story. Root cause: Story Memory's candidate retrieval is real but not exhaustive per Post A2's own
2 documented weight/tier limits; **also** a real, additional Zoom pair (Post #15 vs. Post #18,
different framing of what may be the same disclosed vulnerability) is flagged as a possible second
instance, less certain. Neither was silently hidden — both are called out plainly in the review
packet.

## 12. Whether the Zoom regression is fixed

**No — disclosed, not silently claimed fixed.** Directly measured against the real 23.1O titles
offline (Part A2/Part I case 8): `combined=0.05`, both `NEW_STORY`. This phase's changes do not
touch the underlying `score_candidate()` matching function at all, so this real, exact pair would
still not match today. A **new, live example of the same failure class** appeared in this very
canary (§11 above, Lightcap pair) — direct, current confirmation the underlying recall limit is
real and ongoing, not a one-off from 23.1O.

## 13. Whether the Supermassive regression is fixed

**No — same disclosed limitation** (Part A2/Part I case 9): best real pairwise score 0.523, below
the 0.65 confidence floor required for suppression. Not touched by this phase's changes (matching
function itself unmodified). The real Supermassive Games PC Gamer story (never delivered in
23.1O) was delivered cleanly in this canary (Post #4) with no duplicate present this time (the
GamesIndustry.biz/PC Gamer siblings were not re-collected/re-delivered), so no live re-test of this
specific pair occurred, but the underlying scoring math is unchanged and already measured.

## 14. Whether a real UPDATE occurred

**Yes — 1 real `story_update` classification** occurred live during the window (confirmed in the
`NewsEventStoryLink` data), though it did not happen to be among the 20 delivered posts (its
underlying event did not independently clear the content-generation score/batch selection this
run) — so its downstream delivery behavior (allowed, per design) was not directly observed in a
delivered post this run, only its correct classification.

**Separately, a real, delivery-relevant gate-timing anomaly was found (§14 below is the Terraria-
class question — see §22–24)**: Post #16 (Zuckerberg AI regulation) is the single most important
live finding of Step 9's own observability requirement — see §22–24.

## 15. Offline evidence that UPDATE handling works

**Yes**, independent of the single live occurrence above: `tests/test_story_duplicate_guard.py::
test_orchestration_v1_would_block_but_v2_delta_shows_real_new_information_allowed` (new, passing)
proves, using a real syndicated-wire headline pair with a genuine new `$3 Trillion` figure, that a
SEMANTIC_DUPLICATE match_type with real new information correctly is NOT suppressed
(`would_suppress=False`) — the exact "UPDATE may deserve a new post" behavior Part A3 required,
demonstrated end-to-end through the real delivery-time guard, not just the pure delta function in
isolation. `tests/test_story_suppression.py`'s own pre-existing parametrized tests independently
confirm the same policy at the pure-function level for all match-type/confidence/delta
combinations.

## 16. Number of analyzed source articles containing quotes

Of the 20 delivered posts, **13/20** had a `FULL_TEXT`/`PARTIAL_TEXT` article acquisition (real,
substantial source text available, 3,332–17,875 chars) — a reasonable proxy for "contained
potential quote material," consistent with Phase 23.1O's own equivalent measurement (56% there,
65% here).

## 17. Number containing editorially useful quotes

At least **1 confirmed** (Post #1, Brad Lightcap's own real quote, verified genuine — see §18).
Given the 12 other FULL_TEXT-available posts were not manually read end-to-end for quote content
(time-bounded), this is a floor, not a ceiling — the important, confirmed fact is that useful
quotes ARE now reaching Copywriting, proven at least once, live, for the first time in this
project's history.

## 18. Number of final posts using quotes

**0 rendered**, despite **1 genuinely extracted and verified**. Post #1's `quote` field:
`{"text": "to start something new", "translated_text": "начать что-то новое", "speaker": "Брэд
Лайткап"}` — real, verbatim, correctly translated, correctly attributed. It never appears in the
delivered card text. See §19 for the exact reason.

## 19. Where quotes previously disappeared — and a second gap found live

**Original 23.1O gap (fixed this phase)**: `capabilities/copywriting_capability.py::
_format_quote_source_excerpt()` read only `news_event.content` (thin RSS stub), never the richer
already-acquired article text. **Confirmed fixed** — Post #1 proves a real quote now reaches and is
extracted by Copywriting.

**New gap, found only by this live canary (23.1O had zero quotes, so this was structurally
invisible until now)**: the ACTIVE V8.5 renderer, `services/news_telegram_presentation.py::
render_v81_news_card_html()`/`build_v81_news_body()`, **never reads `copywriting_output.get
("quote")` at all** — confirmed by direct code reading, not assumption. The codebase's own
quote-rendering machinery (`services/quote_budget.py`'s whole-or-omit splice, `worker/
content_cycle.py`'s `quote_telegram_rendering_mode` lookup/resolve, `bot/formatting.py::
render_editorial_card()`) is real and correctly built, but is entirely scoped to the LEGACY
(pre-V8) card format, which V8-family output (the actual accepted format since Phase 23.1J.1,
including V8.5) bypasses completely. Additionally, `quote_telegram_rendering_mode=shadow`
(confirmed) means even the legacy path would only log "would render," never actually pass the
quote through, independent of the V8-family issue. **This is a genuinely new, real, disclosed
finding — not something Part B's own narrow fix could have anticipated, since Phase 23.1O never
had a quote to test rendering against.** Per the phase's own strict stop condition ("do not run
another live canary automatically"), this is NOT patched in this phase — reported for human
decision.

## 20. Exact quote-related change made

See §2. Summary: `capabilities/executor.py` (new `quote_source_text` population, ~35 lines),
`schemas/capability.py` (+1 field), `capabilities/copywriting_capability.py` (`_format_quote_
source_excerpt()` prefers the new field; excerpt cap 3000→6000). No change to Research,
Intelligence, `article_acquisition_mode`'s own gating, or the rendering layer (§19's newly-found
gap is explicitly NOT fixed this phase).

## 21. Whether average/typical copy length increased

**No.** All 20 delivered posts: `main_body` collapsed to exactly one paragraph (unchanged
structural guarantee, `_collapse_to_one_paragraph()` untouched). Character lengths (full HTML)
ranged similarly to Phase 23.1O's own 266–594 range; no post grew because of quote-related changes
since no quote was ever actually rendered (§19). The `_QUOTE_SOURCE_EXCERPT_CHARS` increase
(3000→6000) affects only the PROMPT INPUT Copywriting receives, never the output length ceiling,
which is a completely separate, untouched mechanism.

## 22. Root cause of the Terraria editorial-gate inconsistency

`_is_weak_evidence()`'s `FETCH_FAILED` branch unconditionally returned "not weak," regardless of
whether the event's own `news_event.content` was itself substantial — an unchecked assumption from
one prior real case (Amazon/Gilroy) that did not hold universally. Terraria's real `news_event.
content` was 59 chars (shorter than its own 122-char title) yet was still treated as "not weak,"
letting a story Intelligence explicitly recommended against publishing slip past SKIP into BRIEF.
Full field-level trace in `docs/phase23_1p_offline_acceptance.md` cases 19/24 and the phase's own
working notes.

## 23. Exact deterministic gate behavior after the fix

`classify_editorial_treatment()`'s contract is unchanged in shape (still SKIP/BRIEF/STANDARD/MAJOR
from significance + recommendation + evidence + score); only `_is_weak_evidence()`'s FETCH_FAILED
branch gained one explicit, disclosed sub-check: `FETCH_FAILED` now counts as weak evidence UNLESS
the event's own content demonstrably exceeds its own title in length (real, already-available data,
not a new external signal, not a blind keyword match on the recommendation text — the
recommendation-matching itself was already correct and is untouched).

## 24. Whether any story violated the fixed gate during the live run

**No recurrence of the exact Terraria bug** (no FETCH_FAILED-plus-thin-content story with a
negative recommendation was delivered this run). **However, a different, real gate-timing race WAS
found** (Post #16, Zuckerberg AI-regulation story): re-running the identical, now-fixed classifier
against the same event's current DB state produces SKIP (`HEADLINE_ONLY`, correctly weak), yet the
post was delivered. Timing evidence: the article-acquisition row was written at `19:52:52.912`,
within ~20ms of the treatment-check's own task-creation timestamp (`19:52:52.892`) — strongly
suggesting the treatment check ran a moment before acquisition completed, saw no acquisition row
yet, fell back to `source_reliability` (which passed), and only moments later did the stricter
signal become available. **This is NOT the Terraria bug reappearing** — a structurally different
mechanism (timing/ordering vs. a wrong "not weak" default) — but it IS a real, disclosed, newly-
observed source of gate nondeterminism, worth a human decision on whether editorial-treatment
evaluation should be deferred until acquisition is confirmed complete (a real architecture question,
out of this phase's narrow scope to decide unilaterally).

## 25. Fact Safety PASS/REVIEW/BLOCK counts

**10 PASS / 7 REVIEW / 3 BLOCK** (20 total). All 3 BLOCKs manually classified (full detail in the
review packet): Post #12 ("ИИ-агента Grok Bot" unsupported entity) — LIKELY FALSE POSITIVE
(entity-matching artifact). Post #14 (the literal string "ИИ" flagged unsupported) — LIKELY FALSE
POSITIVE (mechanical token-matching on a 2-letter generic abbreviation, matching the exact
Phase 23.1O "ГБ" pattern). Post #17 (RBC/Moneris) — TWO findings: "RBC" unsupported — likely false
positive (abbreviation-vs-full-name); "2 млрд канадских долларов" uncertain against a conflicting
"1,4 млрд долларов" figure in the source evidence — **UNCERTAIN, a real, worth-human-review
currency/precision discrepancy**, not dismissed as a false positive. Shadow mode correctly
suppressed nothing — all 20 sent regardless of verdict.

## 26. Image success/fallback counts (observation only, frozen)

**13/20** delivered posts carried a real image; all real, on-domain (Techmeme, TechCrunch, CNET,
3DNews, Engadget — no aggregator thumbnails, no generic logos observed). **7/20** correctly had no
image (0 candidates existed in every case checked — never a good image wrongly rejected). No image
scoring, discovery, duplicate-guard, or threshold code was touched this phase, per Part E.

## 27. Runtime

**1h 36m 41s** (`2026-08-11T18:17:23`–`19:54:04 UTC`, 5801s) — stopped by the **hard delivery cap**
(20/20), not the 2-hour clock. A valid, intended stop condition (Part J: "Stop immediately when ANY
cap is reached"), not a violation — natural volume this run was simply higher than Phase 23.1O's
(16 posts in a full 2h there vs. 20 in 1h37m here), consistent with "natural sample, not a forced
target" since no threshold was touched.

## 28. Analyzed-event count

**75/100** (cap never reached).

## 29. Delivered-post count

**20/20** (hard cap exactly reached, never exceeded — `cap.attempted <= 20` asserted and verified
programmatically at process exit).

## 30. API cost

**$0.563006** of the $2.00 cap (28%). By capability: RESEARCH $0.099, INTELLIGENCE $0.135,
ENGAGEMENT $0.131, SCORING $0.054, COPYWRITING $0.125, QUALITY (Fact Safety) $0.019. 336 total
`AIExecution` rows.

## 31. Errors/retries

**1 isolated failure** out of 74 analyzed candidates (1.35%, consistent with Phase 23.1O's own
1.4%) — the same class of Research structured-output floor-validation failure ("Show HN" style
post), self-contained, non-cascading. **0 provider retries** (`retry_number > 0`) across all 336
AI executions. **0 Telegram send failures** across 20 real sends. **0 destination violations.**

## 32. Exact running-process/container state before and after

**Before**: only `ai_newsroom_postgres`/`ai_newsroom_redis` running (confirmed via `docker ps`
immediately before launch); no Python processes; no application worker ever started this session
prior to the canary. **After**: identical — only `postgres`/`redis` running (confirmed via `docker
ps` immediately after the canary process exited), zero stray Python processes (confirmed via
`Get-Process`). No Docker action of any kind was taken this phase (unlike Phase 23.1N.1/23.1O,
Docker Desktop was never restarted this session, so the restart-policy risk never recurred).

## 33. Temporary config changes and restoration confirmation

**In-process only, for the canary script's own process lifetime, never written to `.env`:**
`editorial_delivery_mode="router"`, `copywriting_prompt_version="8.5"` (already the accepted
frozen version), `content_generation_dry_run=False`, `story_memory_mode="shadow"` (real `.env`
value: `off`), `newsroom_telegram_chat_id`/`news_topic_id` (real `.env` value: unset/`None`).
**Restoration confirmed directly from the canary's own final log line**: `=== story_memory_mode
restored to 'off' (in-process only, never touched .env) ===`. `telegram_story_reply_mode` was
deliberately never touched (stayed `off` throughout, matching the real `.env`). `fact_safety_mode`
was read, never overridden (stayed `shadow`, the real `.env` value). `.env` itself was never opened
for writing at any point this phase.

## 34. Regression-test results

All new/modified test files pass: `tests/test_editorial_treatment.py` (17/17, 5 new),
`tests/test_copywriting_capability.py` (22/22, 2 new), `tests/test_capability_executor.py`
(19/19, 3 new), `tests/test_quote_lookup.py` (3/3, all new), `tests/test_story_duplicate_guard.py`
(all pass, 1 new formal test + 1 existing test extended with V2 assertions), `tests/
test_story_memory_v2_shadow_isolation.py` (7/7, 2 intentionally rewritten to reflect the new,
deliberate V2-wiring decision — not deleted, evolved with full justification). Broader regression
(`test_router_media_integration.py`, `test_content_worker_cycle.py`, copywriting v8.2/v8.3/v8.4
suites): 91 passed, 2 failed (pre-existing `.env` `content_generation_dry_run` mismatch, unrelated
to this phase, already documented in Phase 23.1N.1's own report), 12 errors (pre-existing
teardown-only FK pattern, confirmed via isolated re-run showing "N passed, 1 error" for each). Zero
regressions attributable to this phase's own changes anywhere.

## 35. All files changed

**Production code** (7 files): `services/editorial_treatment.py`, `services/story_duplicate_guard.py`
(both pre-existing from Phase 23.1G/23.1I, edited), `services/triage_orchestrator.py`,
`capabilities/executor.py`, `capabilities/copywriting_capability.py`, `schemas/capability.py`,
`worker/content_cycle.py`. **Reused, NOT modified**: `services/story_delta_engine.py`, `services/
story_confidence.py`, `services/story_suppression.py`, `services/article_cleaning.py` (all
pre-existing Phase 20/19 code, imported as-is). **Tests** (6 files): `tests/test_editorial_
treatment.py`, `tests/test_copywriting_capability.py`, `tests/test_capability_executor.py`,
`tests/test_story_duplicate_guard.py`, `tests/test_story_memory_v2_shadow_isolation.py` (all
edited), `tests/test_quote_lookup.py` (new). **New docs**: this report, `docs/
phase23_1p_offline_acceptance.md`, `docs/phase23_1p_story_memory_quotes_gate_review.md`.
**New scripts** (offline-only, not production): `scripts/_phase23_1p_2h_canary.py`, `scripts/
_phase23_1p_post_run_analysis.py`, plus scratch investigation scripts.

## 36. Whether any architecture was changed

**No new subsystem, no new persistence, no embeddings, no new external service, no migration
applied.** Every change either (a) wires already-existing, already-tested modules into a real
code path for the first time (Story Memory V2, quote-source-text), or (b) adds one narrow,
self-relative check to an existing decision function (`_is_weak_evidence()`). The V2 shadow-column
migration (`3c22be05f4e5`) remains unapplied; `NewsEventStoryLink`'s ORM model is unchanged.

## 37. Whether any permanent worker/config/VPS action occurred

**No.** No `.env` edit, no migration applied, no Docker container started beyond the
already-running `postgres`/`redis`, no enforce mode enabled, no VPS action of any kind.

---

## Newly-discovered items requiring human decision before Phase 23.2

1. **Quote rendering gap** (§19): a verified, correctly-extracted quote cannot currently reach a
   real V8.5 delivered card under any configuration — the active renderer never reads the `quote`
   field. Needs a deliberate design decision (splice into `render_v81_news_card_html()` directly?
   weave into `main_body` via a prompt instruction instead? a new, minimal V8.6 successor version?)
   — explicitly NOT decided or implemented here, per Part D's "smallest possible successor version,
   never mutate frozen prompts" instruction and the strict stop condition.
2. **Editorial-gate timing race** (§24): article acquisition and treatment evaluation can race
   within the same content-generation flow, producing a different (weaker) evidence signal if
   re-checked moments later. A real, disclosed nondeterminism, not caused by this phase's own fix.
3. **A live example of the Zoom-class duplicate-recall gap recurred** (§11, the Lightcap pair) —
   direct, current confirmation the architectural limit identified in Part A is real and ongoing.

## Recommendation: **B — SMALL FIX REQUIRED BEFORE VPS**

The three original, named gaps this phase set out to close are each genuinely, meaningfully
improved: Story Memory now runs live with real, correct classification (proven on real syndicated-
wire duplicates); quotes now genuinely reach Copywriting with real, verified content (proven live
for the first time); the exact Terraria regression did not recur. This is real, substantive
progress, not cosmetic.

However, per the phase brief's own explicit instruction ("Do not choose A merely because the tests
pass. Base the recommendation on real editorial behavior"), two new, real, disclosed gaps were
found by this phase's own live testing that did not exist as known issues before today: the quote-
rendering gap (§19) means the quote fix's real-world benefit is currently zero for any delivered
post, and the gate-timing race (§24) means the editorial gate's determinism has a real, if narrow,
exception beyond what Part C's own fix addressed. A duplicate-delivery pair also occurred live
(§11). None of these are severe (no fabricated fact, no wrong destination, no runaway cost/volume,
no unsafe content) — but per the brief's own explicit standard, they are exactly the kind of "small
fix" this decision option describes, not a reason to block further work entirely (C) nor to declare
full readiness (A).

## STRICT STOP

Forensic analysis, necessary narrow fixes, offline acceptance (24/24 cases documented), ONE
2-hour-bounded live canary (stopped early by its own hard cap, a valid outcome), human review
packet, and this report are complete. No Phase 23.2 work, no VPS action, no enforce mode, no
further live canary, no redesign of images/Copywriting/routing performed or attempted. Awaiting
human review.
