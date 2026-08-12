# PHASE 23.1B — LOCAL LIVE NEWSROOM CANARY

**Status: BLOCKED before any Telegram delivery. Zero messages sent. Stopped per Step 5's own
"repeated failures" rule, not attempted again.**

## Environment

- Branch: `feature/phase19-editorial-depth-upgrade`
- HEAD: `d509566154368bf42d54e7dd66166712d77409cb` (unchanged, no commit made)
- DB revision: `8faedf40f596` (Alembic head `3f37cf34109d`, two migrations remain unapplied,
  unchanged)
- `.env`/`.env.example`: untouched (`git status --short` empty)

## Configuration

Applied **in-process only**, inside a single one-shot script (`scripts/
_phase23_1b_local_live_canary.py`), never written to `.env`:

| Setting | Value used |
|---|---|
| `editorial_delivery_mode` | `router` |
| `copywriting_prompt_version` | `6` |
| `story_memory_mode` | `shadow` |
| `fact_safety_mode` | `shadow` (already live, unchanged) |
| `newsroom_telegram_chat_id` | `-1004297182444` |
| `news_topic_id` | `2` |
| `content_generation_dry_run` | `False` (a real, live run — the whole point of this canary) |

A hard preflight assertion (`resolve_route(EditorialDestination.NEWS) ==
RouteTarget(chat_id=-1004297182444, topic_id=2)`) ran before any cycle — confirmed correct, printed
in the run log, before any LLM or Telegram call was made.

## Workers

**Started**: nothing new as a persistent service. One bounded, one-shot Python script run directly
on the host (not Docker), mirroring `worker/analysis_main.py`/`worker/content_main.py`'s own real
construction (`assemble_ai_integration_layer`, `build_model_registry`, `FilePromptRepository`,
`ModelRegistryPricingCatalog`, `create_bot`) minus their `while True` loop — exactly one
`run_analysis_cycle()` call (capped at `news_analysis_batch_size=5`) followed by exactly one
`run_content_cycle()` call (capped at `content_generation_batch_size=5`).

**Already running, untouched**: `automation_worker` (Collection + Triage — the source of the fresh
NEWS_ANALYSIS backlog), `telegram_bot` (polling container — my script opened its own independent
`Bot` client via the same `create_bot()`, unrelated to the running polling loop).

**Not started**: `content_worker`, `news_analysis_worker` (Docker containers) — the equivalent real
functions were called directly instead, for tighter, precisely-bounded control. Confirmed still
`Exited (1)` after this run.

## Processing

- **NEWS_ANALYSIS**: `eligible_found=5, claimed=5, completed=5, failed=0` — all 5 fresh-eligible
  tasks (within the 2h freshness cutoff) completed successfully, each with real Research/
  Intelligence/Scoring LLM calls.
- **CONTENT_GENERATION**: `eligible_found=4, completed=0, failed=4, notified=0` — all 4 fresh-
  eligible events (3 that were already `NEWS_ANALYSIS(COMPLETED)` before this run, plus 1 more that
  became eligible after the analysis cycle above) went through Research reuse + real Copywriting
  (V6) + Quality + Fact Safety successfully — **every one of the 4 underlying `EditorialTask` rows
  is `COMPLETED`, with real V6 output persisted in `workflow.step_results`** — but **every one then
  failed at the final `ContentDraftService.create_from_result()` step**, before a `ContentDraft` row
  was ever created. See "Problems discovered" below.
- **Telegram messages delivered: 0.** `send_editorial_card`/`send_to_editorial_destination` were
  never reached for any of the 4 events — delivery is only attempted after a `ContentDraft` exists.
  Confirmed directly against the database: 0 `ContentDraft` rows exist for any of the 4
  `CONTENT_GENERATION` task ids.

## Cost

Real, measured via `AIExecution.cost` before/after (`SUM`, not estimated):
- Baseline: `$7.186309`
- Final: `$7.227567`
- **Delta this run: $0.041258** — 5 real NEWS_ANALYSIS workflows (4 LLM calls each: Research,
  Intelligence, Scoring, ×2 for two of them showing extra routing decisions) + 4 real
  CONTENT_GENERATION workflows (Copywriting + Quality, Research/Intelligence reused from the
  NEWS_ANALYSIS step per `capability_result_reused_from_news_analysis`) — all real `https://
  api.openai.com/v1/responses` calls, confirmed in the run log (`HTTP/1.1 200 OK` throughout, zero
  provider errors).

## Quality Review

One full real V6 draft was inspected directly from the persisted `EditorialTask.workflow` JSON
(the Roblox stock-drop event) despite never being delivered — genuinely useful signal even though
delivery failed:

- **Relevance**: high — Intelligence correctly scored significance 8/10, identified the real
  editorial angle (investor-confidence crisis, audience decline, revised profit outlook), and
  explicitly recommended publication with verification caveats.
- **V6 writing quality**: **genuinely good, editorial-grade Russian prose** — a real opening hook,
  concrete context, substantive "why it matters," a clear "what changed," an honest "what remains
  unknown" section, and correct quote handling (verbatim English original + separate, clearly-
  labeled Russian translation, never fabricated or paraphrased-as-verbatim). This is the first real
  evidence this session that V6's long-form structure produces genuinely publishable-quality output
  from real news input, not just synthetic test fixtures.
- **Fact Safety**: **Phase 21's V6 compatibility fix is confirmed working on a real, live V6 draft**
  — `status: "review"`, `claims_checked: 5`, `3 supported / 2 uncertain / 0 unsupported`,
  `highest_risk: "low"` — a real, non-silent, correctly-populated result, not the pre-Phase-21
  silent no-op. This is the first live confirmation of that fix outside its own test suite.
- **Duplicate handling**: not exercised — `story_memory_mode=shadow` computes matches but never
  suppresses (Phase 20's own unchanged design); no duplicate/related-story signal was observed in
  this small a batch (5 fresh, presumably distinct events).
- **Memory classification**: no `story_context`/match-type data was inspected this round (out of
  scope once delivery itself failed) — deferred to a future run.
- **A real, separate finding from QualityCapability's own LLM judge** (`passed: false`) on the same
  draft: it flagged (1) "the short-content/Body text is missing" — QualityCapability's own prompt
  also assumes a V4-shaped `body` field exists, a **third** place (after the pre-Phase-21 Fact
  Safety gap and `ContentDraftService`, see below) where V4-only assumptions leak into V6 handling;
  (2) the headline doesn't reflect a "decision" mentioned in the source event; (3) the event was
  miscategorized as `HARDWARE` for a gaming/stock story — an upstream categorization issue,
  unrelated to V6 itself. None of these blocked anything (Quality's `passed`/`issues` output has
  never gated delivery in this architecture), but are disclosed as real observations from this
  live run, not smoothed over.

## Telegram

**Confirmed: zero messages were sent to any destination.** No wrong-destination risk occurred —
the preflight route assertion passed, and delivery was never reached for any of the 4 events (all
failed earlier, at draft persistence). Nothing was sent to `-1004297182444`/topic `2`, nothing was
sent to the old `editorial_chat_id`, nothing was sent anywhere else.

## Problems discovered

**Root cause (blocking)**: `services/content_draft_service.py::create_from_result()`, line 160:
```python
title = copywriting_output["title"]
body = copywriting_output["body"]    # <- KeyError for every V6 draft
```
V6's real schema (`prompts/copywriting/v6.yaml`, confirmed in Phase 21's own investigation) has no
`body` key at all — its structure is `opening/context/why_it_matters/what_changed/
what_happens_next/conclusion/what_remains_unknown/quote`. This is a **hard `KeyError`**, not a
silent no-op — it raised inside `create_from_result()`, was caught by `scripts/
run_content_generation.py`'s own existing `except Exception` guard (logged as `content_generation_
completed_but_draft_persistence_failed`, never crashing the cycle or corrupting state — confirmed:
the `EditorialTask` stays cleanly `COMPLETED` with its real step results intact, zero orphaned or
partial `ContentDraft` rows), and surfaced as `ContentCycleResult(completed=0, failed=4)`.

This is the **same class of bug** Phase 21 fixed for Fact Safety (`apply_fact_safety()`'s own
former `copywriting_output.get("body")` guard) — but in a different, more central location that
Phase 21 explicitly did not touch (out of scope: "ONLY fixes V6 Copywriting compatibility with Fact
Safety"). It is more severe here: this is the function that persists **every** `ContentDraft`,
`ContentDraftService` being a hard dependency of the entire delivery pipeline for any prompt
version. **V6 Copywriting has never been able to produce a real, persisted `ContentDraft` in this
codebase** — every real production run to date has used V4 (the default); V6 was previously only
exercised through the Phase 19 manual A/B/C harness, which builds its own `VariantResult` directly
from capability output rather than going through `ContentDraftService`.

**A related, third instance of the same pattern** was also observed live this run:
`capabilities/quality_capability.py`'s own prompt/judgment (§"Quality Review" above) assumes a
`body`-shaped summary exists and flags its absence — not a hard crash (Quality's own capability
still returns `passed: false` + `issues`, doesn't raise), but the same underlying V4-only
assumption surfacing a third time.

**Non-blocking, disclosed**: the sampled event's category (`HARDWARE` for a Roblox stock/gaming
story) looks wrong — a pre-existing categorization concern, unrelated to this canary's own scope,
not investigated further here.

## Recommendation

**NOT ready for Phase 23.2 (VPS Deployment).** More immediately: **not ready for a repeat canary
attempt with `copywriting_prompt_version=6` either**, until `services/content_draft_service.py::
create_from_result()`'s `body` extraction is made V6-compatible — the exact same "adapt to the
schema, don't force V6 backwards" principle Phase 21 already established and proved out for Fact
Safety. Recommend a narrowly-scoped **Phase 23.1C — V6 ContentDraft Compatibility Fix**, mirroring
Phase 21's own investigation-first, test-first process, before any further live delivery attempt:
1. Fix `ContentDraftService.create_from_result()` to derive `title`/`body` from either V4's `body`
   key or V6's narrative sections (the same reduction Phase 21 already wrote and tested for Fact
   Safety, `services/fact_safety.py::_extract_draft_text()` — very likely directly reusable or
   near-identical, rather than inventing a second implementation).
2. Re-examine `capabilities/quality_capability.py`'s own prompt for the same V4-only `body`
   assumption while in the area (disclosed this run, not yet fixed).
3. Only then re-attempt this exact canary script (`scripts/_phase23_1b_local_live_canary.py`,
   unmodified otherwise) to reach an actual, real, human-reviewable Telegram delivery.

**What this run did successfully validate, real and live, not synthetic**: NEWS_ANALYSIS →
Scoring → Research/Intelligence reuse → real V6 Copywriting generation → Phase 21's Fact Safety
V6 fix, all working correctly end-to-end, with genuinely good editorial output quality (§"Quality
Review") — the pipeline up to (but not including) `ContentDraft` persistence is proven live. Cost
was small and bounded (`$0.041` for 9 real workflow executions). Backlog protection held exactly as
designed (5 and 4 items respectively, out of a 15,000+ deep stale backlog, zero stale processing).
Destination safety held with zero risk (nothing was ever sent anywhere, by construction — delivery
was never reached).

---

**STOP condition met** (via the "repeated failures" trigger in Step 5, before ever reaching Step
7's 5-10-message human-review point — zero messages were delivered). Not continuing to VPS
deployment, other content formats, or production rollout. Waiting for review and direction on the
recommended Phase 23.1C fix before any further live attempt.
