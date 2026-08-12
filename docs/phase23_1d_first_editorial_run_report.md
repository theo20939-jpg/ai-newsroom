# PHASE 23.1D — FIRST EDITORIAL RUN (LOCAL LIVE CANARY RETRY)

**Status: SUCCESS — the first real Newsroom editorial draft was generated and delivered live to
the correct Telegram destination.** 1 message sent (below the 5-10 target — see §5/§12 for why),
stopped deliberately rather than chasing volume, per the phase's own "do not chase volume"
instruction.

## 1. Environment

- Branch: `feature/phase19-editorial-depth-upgrade`
- HEAD: `d509566154368bf42d54e7dd66166712d77409cb` (unchanged, no commit made)
- DB revision: `8faedf40f596` (Alembic head `3f37cf34109d`, unchanged, two migrations still
  unapplied)
- `.env`/`.env.example`: untouched (`git status --short` empty, confirmed both before and after)

## 2. Effective configuration

Applied **in-process only**, inside one bounded, one-shot script (`scripts/
_phase23_1d_local_live_canary.py`), never written to `.env`:

| Setting | Value |
|---|---|
| `editorial_delivery_mode` | `router` |
| `copywriting_prompt_version` | `6` |
| `story_memory_mode` | `shadow` (see §10 - inert this run, explained below) |
| `fact_safety_mode` | `shadow` (already live, unchanged) |
| `newsroom_telegram_chat_id` | `-1004297182444` |
| `news_topic_id` | `2` |
| `content_generation_dry_run` | `False` |

A hard preflight assertion confirmed `resolve_route(EditorialDestination.NEWS) ==
RouteTarget(chat_id=-1004297182444, topic_id=2)` before any LLM or Telegram call. Confirmed
reverted to real defaults (`legacy`/`4`/`off`) in a fresh process immediately after the run.

## 3. Started components

Same minimal-footprint approach as Phase 23.1B/23.1D's own preflight: **no new persistent
service**. One bounded host script — one `run_analysis_cycle()` call (capped at
`news_analysis_batch_size=5`) + one `run_content_cycle()` call (capped at
`content_generation_batch_size=5`), real AI layer, real `Bot`. `automation_worker`/`telegram_bot`
already running, untouched. `content_worker`/`news_analysis_worker` remained `Exited` throughout —
confirmed before and after.

## 4. Number of analyzed events

**5** — `AnalysisCycleResult(eligible_found=5, claimed=5, lost_races=0, completed=5, failed=0)`.
All 5 fresh-eligible `NEWS_ANALYSIS` tasks completed successfully with real Research/Intelligence/
Scoring calls.

## 5. Number of drafts

**1** — `ContentCycleResult(eligible_found=1, completed=1, failed=0, notified=1,
notification_failed=0)`. Of the 5 just-analyzed events (plus the 0 already-eligible-but-unconsumed
ones — the 4 from Phase 23.1B are permanently excluded, see Phase 23.1C's own report §7 remaining
risk #4), only **1** cleared `content_generation_min_score=65` and had no existing
`CONTENT_GENERATION` sibling. This is a genuine, honest scoring outcome — not a bug: `Intelligence`
itself scored this batch's *other* stories too low or they were excluded by the freshness/anti-
duplicate join before scoring was even relevant. Per the phase's own explicit "do not chase volume"
instruction, this run was **not** extended with additional cycles to reach the 5-message target —
this single, successful, human-reviewable message is the deliberate stopping point.

## 6. Telegram messages

**1 real message sent, delivered successfully.** Instrumented directly (not inferred): the
canary script wrapped the real `bot.send_message()` call and recorded every invocation's actual
`chat_id`/`message_thread_id`, then asserted them against the real target *inside the script
itself* (so a mismatch would have raised immediately, not merely been noticed after the fact):
```
{'chat_id': -1004297182444, 'message_thread_id': 2}
```
Exactly `-1004297182444` / thread `2` — the real NINJA NEWSROOM NEWS topic. No other destination
was constructed or reachable (`editorial_delivery_mode="router"` hardcodes `EditorialDestination.
NEWS` only, per Phase 23.1A's own structural test). Nothing was sent to the legacy
`editorial_chat_id` (`5507703201`) or anywhere else.

## 7. Cost

Real, measured via `AIExecution.cost` before/after:
- Baseline: `$7.227567`
- Final: `$7.268466`
- **Delta this run: $0.040899** — 5 real `NEWS_ANALYSIS` workflows + 1 real `CONTENT_GENERATION`
  workflow (Research/Intelligence reused from analysis, plus real Copywriting V6 + Quality calls).
  One transient retry was observed and self-healed (`openai._base_client | Retrying request...`,
  `integrations.llm_gateway.fallback.policy | retry`, then a normal `200 OK`) — no manual
  intervention needed, the existing retry/fallback policy handled it correctly.

## 8. V6 quality observations

The one delivered draft (Google Pay India AI story) was inspected directly from the persisted
`EditorialTask.workflow` JSON:
- **Writing quality**: genuinely coherent, honestly-hedged Russian editorial prose — the piece
  correctly conveys uncertainty ("Пока это скорее сигнал о направлении развития... чем
  подтверждённое крупное обновление") rather than overstating a thin announcement. Consistent
  with the Phase 23.1B sample's own quality finding.
- **A real, disclosed editorial-judgment gap, not a code bug**: `Intelligence` scored this story's
  own significance only **3/10** and explicitly recommended **"Не публиковать как полноценную
  новость без дополнительной проверки первоисточника"** ("do not publish as a full news item
  without further source verification") — yet the story was generated and delivered anyway.
  This is pre-existing, disclosed architecture (Intelligence's own textual recommendation has never
  been a hard gate; only the separate numeric `Scoring` result gates `CONTENT_GENERATION`
  eligibility) — not something this canary or its recent fixes touched — but this run is the first
  live, concrete evidence of that gap actually manifesting: a story Intelligence itself advised
  against publishing reached a real Telegram channel. Worth explicit human review and a product
  decision before any wider rollout (§12).
- **The same `QualityCapability`-own-`body`-assumption gap already disclosed in Phase 23.1B/23.1C**
  recurred: `"passed": false`, `"issues": ["Отсутствует основной текст публикации..."]` — Quality's
  own prompt still expects a `body`-shaped field that V6 doesn't produce under that name. Still
  non-blocking (Quality's `passed`/`issues` has never gated delivery), still not fixed this phase
  (explicitly out of scope, tracked in Phase 23.1C's own §7).
- **Image intelligence** (shadow-only, no delivery effect regardless of outcome, since router mode
  never uses the image-preview branch — Phase 23.1A's own design): found 2 candidates, validated
  1 (quality score 66, accepted technically) but marked it `ineligible` for editorial use
  (`generic_aggregator_asset`) — correctly excluded, no image was or could have been attached.

## 9. Fact Safety observations

**`status: "pass"`** — 10 claims checked, 10 supported, 0 uncertain, 0 unsupported, `highest_risk:
null`. Phase 21's V6 compatibility fix continues to work correctly on real, live V6 drafts (second
live confirmation, after Phase 23.1B's own `"review"` result on a different, more claim-dense
story) — this time producing a clean pass on a thinner, more hedged story, exactly the kind of
result variation across real stories that indicates it's genuinely evaluating content, not
returning a fixed value.

## 10. Story Memory observations

**Inert this run — a real, honestly-disclosed limitation of the canary script's own design, not a
code bug.** `story_memory_mode="shadow"` was set in-process before running this script, but Story
Memory is only ever applied at **Triage** time (`services/triage_orchestrator.py::
_apply_story_memory()`), which happens inside `automation_worker`'s own separate, continuously-
running process — under the *real* `.env`'s `story_memory_mode=off` (confirmed live, unchanged).
By the time this canary script's `run_analysis_cycle()`/`run_content_cycle()` ever touched these 5
events, Triage had already run for them (hours or days earlier) with Story Memory off — an
in-process setting override in a *different, later* Python process cannot retroactively change a
decision already made and persisted by an *earlier* one. Confirmed directly: no
`NewsEventStoryLink` row exists for the delivered event. **To actually exercise Story Memory
shadow mode in a future canary, `story_memory_mode=shadow` would need to be active in the real
`.env` (or `automation_worker`'s own process) at Triage time** — a materially different, more
invasive change than this phase's own scope authorized (`.env` changes are explicitly forbidden).
Recommend this be explicitly planned for in any follow-up canary phase rather than assumed already
covered.

## 11. Problems discovered

1. **Story Memory shadow mode was not actually exercised** (§10) — a scope/design gap in how the
   canary script's in-process settings interact with `automation_worker`'s separate process, not a
   regression or a bug in Story Memory itself.
2. **A low-significance story that Intelligence itself recommended not publishing was delivered
   anyway** (§8) — a real, pre-existing architectural gap (Intelligence's recommendation isn't a
   gate) now confirmed live, not newly introduced.
3. **`QualityCapability`'s own `body`-assumption gap** (§8) recurred, exactly as already tracked in
   Phase 23.1C §7 — not fixed this phase, disclosed again for visibility.
4. **A transient OpenAI API retry occurred and self-healed** (§7) — no action needed, existing
   fallback policy worked correctly, noted for completeness.
5. **Only 1 of 5 analyzed events reached delivery** — expected/correct scoring behavior, not a
   defect, but means reaching the "5-10 message" target in one run requires either a larger
   analysis batch or multiple cycles - not attempted this run per "do not chase volume."

## 12. Recommendation for next phase

**NOT ready for Phase 23.2 (VPS Deployment) yet** — this was the *first* successful live delivery,
a single data point, not a validated batch. Recommend, before any further scale-up:

1. **Human review of this one message** (in the real Telegram group) is the immediate next step —
   the phase's own Step 7 requirement ("prepare results for editorial review") is satisfied by this
   report; the actual review is a human action, not something this phase can complete unilaterally.
2. **A product decision on Intelligence's advisory recommendation** (§8, §11.2) — should a low
   `significance` score or an explicit "do not publish" recommendation from Intelligence become a
   real gate (mirroring how `Scoring`'s numeric result already gates eligibility), before more
   volume is generated unattended? This is an editorial/product decision, not a code fix this
   report can make unilaterally.
3. **If more volume is wanted to reach the original 5-10 message target**, a follow-up run
   (Phase 23.1E or a continuation) using the same, now-proven script and fix is low-risk and cheap
   (~$0.04 for this entire run) — but should be a deliberate, separately-authorized next step, not
   assumed.
4. **If Story Memory shadow-mode observation is actually wanted** in a future canary, it requires
   either a real (reviewed, temporary) `.env` change for `automation_worker`, or restructuring the
   canary to also run Collection+Triage itself in-process (a larger scope change) — flagged for
   explicit planning, not assumed solved by this run's own settings.

---

**STOP condition met.** 1 successful NEWS message delivered and confirmed correctly destined.
Not continuing to VPS deployment. Waiting for human review of the delivered message and direction
on §12's open decisions before any further live run.
