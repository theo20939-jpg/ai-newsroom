# Phase 23.1O — Final 2-Hour Combined NEWS Canary — Final Report

Branch `feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(unchanged, nothing committed). Local-only: real Postgres/Redis, real external sources, real paid
LLM calls, real Telegram sends to the one approved destination. No VPS, no other Telegram
destination, no enforce modes, no new Copywriting version.

## 1. Executive summary

A genuinely time-bounded (not volume-targeted) 2-hour observation of the accepted NEWS pipeline
running against real, fresh incoming news. 140 real events collected, 74 fully analyzed, 16
delivered to the real NEWS topic — all within the emergency hard cap (16/20) and cost cap
($0.53/$2.00), stopped by the intended primary boundary (`runtime_reached`, not either cap).
Text/language/story-angle/image quality are largely strong and consistent with prior canaries.
Two real, evidence-backed gaps surfaced that did not show up in earlier small-sample canaries:
(1) a near-certain **duplicate story** (the same Zoom vulnerability, two outlets) was delivered
twice with nothing to stop it, and a second near-duplicate cluster (Supermassive Games layoffs,
3 outlets) was saved only by chance, not protection — both trace directly to `story_memory_mode=off`,
this project's own currently-accepted configuration; (2) one concrete case where Intelligence's own
"do not publish without verification" recommendation did not prevent delivery. Neither is a new
regression from this phase's own code — both are pre-existing architectural gaps this canary's
larger, longer sample was specifically able to surface. See §24 for the recommendation this drives.

## 2. Exact runtime window

- `CANARY_START`: `2026-08-11T14:52:55.524863+00:00`
- `CANARY_END`: `2026-08-11T16:53:03.484971+00:00`
- Duration: 7211.2s (2h 0m 11s — the script's own tick granularity, ~30s over the 7200s target)
- Stop reason: **`runtime_reached`** — the primary boundary. Neither the hard delivery cap (16/20
  attempted) nor the cost cap ($0.53/$2.00) was ever the actual trigger.

## 3. Preflight state

Read directly from the environment immediately before starting (not assumed from prior reports):

- Branch/HEAD: unchanged from Phase 23.1N.1's own recorded state.
- Working tree: unchanged, same accumulated uncommitted files.
- Real dev DB Alembic revision: `8faedf40f596` (behind file-based head `3f37cf34109d` — the same
  intentionally-unapplied-migrations state as every prior phase; not touched).
- Docker: only `ai_newsroom_postgres`/`ai_newsroom_redis` running before start (the preferred safe
  state) — `content_worker`/`news_analysis_worker` stayed stopped throughout, since this canary
  runs the real pipeline functions in-process rather than via those containers (see §4).
- Settings read live from the `Settings` object (not `.env` grep alone): `fact_safety_mode=shadow`,
  `story_memory_mode=off`, `editorial_delivery_mode=legacy` (overridden to `router` in-process for
  the run), `copywriting_prompt_version=4` (overridden to `8.5` in-process), `content_generation_dry_run=False`,
  `image_intelligence_mode=shadow`, `image_candidate_persistence_mode=finalists`,
  `image_editorial_preview_enabled=True`, `news_collection_enabled=True`, `news_analysis_enabled=True`.
- Backlog (via the REAL production selectors, `worker.analysis_cycle._select_eligible_task_ids` /
  `worker.content_cycle._select_eligible_events`, called read-only): NEWS_ANALYSIS had 17,543 total
  pending `CREATED` tasks accumulated across the project's whole history, but only 81 within the
  2-hour freshness cutoff (`news_analysis_freshness_cutoff_hours=2.0`) — the other 17,462 are
  structurally unreachable (SQL `anchor >= cutoff` filter), confirmed by direct code reading, not
  assumption. CONTENT_GENERATION had 0 currently eligible (score≥65 AND fresh AND no existing task)
  before the canary started.
- Destination proof: `resolve_route(EditorialDestination.NEWS)` → `RouteTarget(chat_id=-1004297182444,
  topic_id=2)`, asserted in-process before the run began; every other destination
  (MEME/TELEGRAPH/INSTAGRAM/REELS) resolves to the same chat's root (`topic_id=None`, no thread) under
  this run's settings — never a different chat — and is structurally unreachable anyway, since
  `worker/content_cycle.py`'s router branch is hardcoded to `EditorialDestination.NEWS` only (confirmed
  by direct code reading, not merely cited from a prior report).

## 4. Components started

No Docker application containers were started for this canary. `scripts/_phase23_1o_2h_combined_news_canary.py`
runs as a single local Python process that calls the real, unmodified pipeline functions directly
(`worker.cycle.run_automation_cycle` [collection+triage], `worker.analysis_cycle.run_analysis_cycle`,
`worker.content_cycle.run_content_cycle`) on a fine-grained scheduler loop that ticks each stage at
its own real, already-configured production cadence — not invented: `news_collection_interval_seconds`
(1800s), `news_analysis_poll_interval_seconds` (300s), `content_generation_poll_interval_seconds`
(1800s), all read live from `settings`. This is the same "call the real cycle functions directly"
pattern every prior canary (23.1A–23.1N) already used, extended from a single round-loop to a
multi-cadence scheduler bounded by wall-clock time instead of a message count.

## 5. Safety controls

- **Hard delivery cap**: Phase 23.1L's own `HardDeliveryCap`/`wrap_bot_with_hard_cap` (`scripts/_canary_delivery_cap.py`),
  reused byte-for-byte, unmodified — enforced at the real `bot.send_message`/`bot.send_photo` call
  site, checked before every real Telegram API call, not per-round. `max_deliveries=20`. Final: 16/20
  attempted, never exhausted.
- **Cost cap**: $2.00, checked every scheduler tick against the real `sum(AIExecution.cost)` delta.
  Final: $0.5313.
- **Runtime cap**: 7200s, the primary boundary. Final: 7211s (tick granularity).
- **Destination**: hardcoded `_REAL_CHAT_ID`/`_REAL_NEWS_TOPIC_ID` constants in the script, asserted
  against `resolve_route()` before the run started, and every one of the 16 real sends was recorded
  and verified post-hoc — 0 sends to any other chat_id/thread.
- **Settings**: all overrides in-process only (`settings.editorial_delivery_mode = "router"` etc.),
  never written to `.env`. `fact_safety_mode`/`story_memory_mode` were read and logged, never
  overridden — left at whatever the real `.env` already has.

## 6. Volume

Natural, not manufactured — no message-count target existed in this run's own stop conditions:

- 140 new real events collected across 4 collection cycles (from 1,874 total source-fetch attempts
  across those cycles, ~469 real distinct sources each pass)
- 140 EditorialTask(NEWS_ANALYSIS) created (1:1 with collected events, all claimed)
- 75 analysis tasks became eligible and were claimed across 15 analysis cycles; 74 completed, 1 failed
- 16 content-generation tasks became eligible across 4 content cycles; all 16 completed; all 16 delivered
- **16 real Telegram NEWS posts sent** — this was the natural output of a 2-hour window under the
  accepted thresholds, not a chosen target.

## 7. Selection quality

Of 74 fully-analyzed real candidates: 45 scored below the `content_generation_min_score=65` gate
(mostly correctly — see §8), 1 was explicitly gated `SKIP` by Editorial Treatment (a low-reliability
neuroscience-AI story Intelligence itself recommended against, and Treatment correctly honored that),
12 scored ≥65 and were never picked up simply because the 2-hour window ended before their turn in
the 30-minute content-generation cadence (a real, disclosed recall gap — see §22), and 16 were
delivered. Of the 16 delivered: `main_body_paragraph_count == 1` for **all 16** (100% structural
compliance), 9/16 had a real, relevant, own-domain image, 7/16 correctly had no image (0 candidates
existed — never a rejected-good-image case), and every single one carried a working source button.

## 8. Skipped-news quality

A 21-item representative sample (`scripts/_phase23_1o_skipped_sample.json`) spanning all four skip
classes:

- **Low score, clearly correct** (e.g. two "Код Дурова" Telegram-channel posts scoring 3–5,
  informal/social, not news; a puzzle-game store listing scoring 48) — low-score filtering is
  working as intended on genuinely low-value candidates.
- **Low score, more debatable** (e.g. a "Человек-паук" film-driving-game-sales story scored 62 despite
  Intelligence itself rating its significance 72/10 internally-inconsistent-looking — worth a human
  look, not necessarily a defect, since score and raw significance are computed by different steps).
- **Treatment SKIP (1 case)**: "Новый ИИ расшифровывает, как области мозга общаются" — score 72 (passed
  the content-gen threshold) but Treatment correctly gated it `SKIP` for "weak evidence (low source
  reliability) + explicit negative Intelligence recommendation." This is the gate working exactly as
  designed — contrast with §18/Post #2 below, where a similar negative recommendation was NOT honored.
- **Passed score, simply not yet reached (12 cases)**: several genuinely solid stories (TSMC/Sony
  $4.69B JV announcement, an iOS 27 leak, a Lenovo foldable-OLED laptop, Zuckerberg's "personal
  superintelligence" essay, a French-publishers-vs-Google-AI-Overviews antitrust story, New Orleans'
  AI 911 triage, two more independent Supermassive Games layoff articles) sat correctly-scored and
  correctly-treated in the queue, undelivered only because the 2-hour window ended first. This is a
  genuine recall signal, not a rejection — worth noting for §22/§24, not a defect to fix reactively.

## 9. Text quality

All 16 delivered posts: HEADLINE + exactly ONE main-body paragraph + optional ending (8/16 have one).
Character length (full HTML incl. tags) ranged 266–594, average 415 — well under any ceiling, no
padding observed. The specific repetitive phrase the brief called out, "неизвестно," appeared **0
times** across all 16 bodies/endings; other legitimate hedging phrases ("не раскрыт-," "не уточня-,"
"не подтвержд-") appeared but were spread across different posts (max 4/16 for any one phrase), each
used to flag a real, genuine evidence gap rather than as filler.

## 10. Russian-language quality

Generally natural and precise. Two concrete, worth-human-review defects found (not patched, per the
brief's explicit "do not fix during the canary" instruction):

- **Post #2** (Terraria mod): the headline "Авторы мода... рассказали об утрате интереса к проекту"
  ("...talked about losing interest in the project") is a softened, materially different framing from
  the real event (the mod's own decade-long shutdown over a "irrecoverably tainted reputation" and
  grooming allegations) — headline weaker than the evidence, the exact defect class Step 12 asked to
  watch for.
- **Post #16** (RTX 4080 32GB): headline says the modified cards "appeared on the secondary market";
  the source says China has begun **mass production** of them — again headline softer than the source.

No calques, no awkward participial overloading, no wrong verb choice, and no unnecessary jargon were
found in this sample of 16.

## 11. Story-angle preservation

2/16 delivered posts were classified `story_led: true` (Post #5, Research Gold; Post #14, the Zoom
"Zoomsday" hack). Both preserve WHO/WANTED WHAT/WHAT HAPPENED/WHAT MADE IT UNUSUAL cleanly (full text
in the review packet) — the structure is not forced onto the other 14, ordinary fact-led items, which
correctly stayed plain declarative sentences.

## 12. Viral/meme observations

Among the 16 candidates that actually reached Copywriting (the only stage that computes these
signals): `viral_potential` — 6× MEDIUM, 10× LOW, 0× HIGH, 0× NONE. `meme_potential` — 6× LOW, 10×
NONE, 0× MEDIUM, 0× HIGH. **No MEDIUM/HIGH meme_potential candidates were observed this run** — an
honest null result for the future-MEME-phase backlog, not a defect; this canary's real news sample
simply didn't contain a strongly meme-shaped story in this window.

## 13. Duplicate behavior — the most significant finding

**Confirmed duplicate delivery.** Post #3 (9to5Mac, 15:31 UTC, "Zoom flaw let an attacker take over
your device, including iPhone and Mac") and Post #14 (The Verge, 16:44 UTC, "'Zoomsday' hack
uncovered using fewer than 20 AI prompts") describe what is, on the evidence, the same real Zoom
vulnerability disclosure — device takeover of meeting participants, discovered with AI-assisted
security research — reported by two different outlets 73 minutes apart. Both were delivered as
separate NEWS posts. `story_id` is `null` for both.

**Root cause, confirmed directly from real counters, not inferred**: every one of the 4
collection+triage cycles this run logged `story_new=0, story_updates=0, story_semantic_duplicates=0,
story_related=0` — Story Memory's own semantic-duplicate computation never ran at all, because
`story_memory_mode=off` (this project's own currently-accepted real configuration, left untouched per
the phase brief's explicit instruction). This is not a bug introduced by this canary or by Phase
23.1N.1 — it is a direct, now-directly-observed consequence of running the accepted pipeline with
Story Memory off, exactly the kind of real evidence Step 18's own "we need evidence first" principle
was asking this canary to gather.

**A second, near-miss cluster**: the real Supermassive Games layoff story had **three** independent
source articles in the pipeline this run (3DNews — delivered as Post #7; GamesIndustry.biz and PC
Gamer — both sitting correctly-scored, correctly-treated, and undelivered only because the window
ended first, §8). Nothing in the current architecture would have stopped either from being delivered
as a second or third separate post had the window run longer — `_select_eligible_events`'s own
duplicate-resend guard is keyed on `event_id` (i.e. "this exact article was already content-generated"),
never on "a different article about the same real-world event."

No image was duplicated this run (`duplicate_blocked=0` in every content-cycle result, and
`router_image_duplicate_skipped` never appeared in the log) — the cross-event image guard was simply
never exercised, since no image was reused; this is a null result, not proof of a live catch this run.

## 14. Image quality

9/16 delivered posts carried a real image; all 9 resolved to the article's own domain
(9to5mac.com, theguardian.com ×2, 404media.co, 3dnews.ru ×4, theverge.com) — no tiny aggregator
thumbnails, no generic logos, no stale/irrelevant high-resolution images observed. The 7 text-only
posts all had `image_candidate_count == 0` — confirmed correctly "no candidates existed" in every
case, never a good image wrongly rejected. Phase 23.1N.1's ranking fix was not stress-tested by a
genuine Techmeme-vs-better-source situation this run (none of the 74 candidates happened to reproduce
that exact shape), but no regression of any kind appeared either.

## 15. Fact Safety shadow results

16/16 delivered posts, verdict breakdown: **8 pass, 5 review, 3 block**. Shadow mode correctly never
suppressed anything — all 16 sent regardless of verdict, exactly as configured. Manual classification
of the 3 BLOCKs (full detail in the review packet):

- **Post #14** (Zoom "Zoomsday"): flagged findings are two "unsupported entity" hits on the strings
  "Уязвимость Zoom" and "Исследователи A Security" plus two "uncertain" hits on "20 запросов" — this
  matches the exact entity-matching-not-fact-checking pattern Phase 23.1H's own report already
  disclosed as the dominant class of shadow-mode flags. **Classification: LIKELY FALSE POSITIVE.**
- **Post #15** (Apple iCloud Private Relay lawsuit): flags the quoted phrase "Частный узел" as
  unsupported/uncertain, and its own `issues` list separately notes the headline's word "уязвимость"
  (vulnerability) may overstate what the source actually describes (a potential IP-exposure design
  limitation vs. a confirmed exploit). **Classification: UNCERTAIN** — a plausible mild overstatement,
  worth a human read, not clearly wrong.
- **Post #16** (RTX 4080 32GB): the flagged "unsupported entity" is the literal string "ГБ" (the unit
  abbreviation "GB"), flagged twice — a mechanical tokenization artifact, not a substantive claim.
  **Classification: LIKELY FALSE POSITIVE.** (The same record's `issues` list separately, correctly
  flags the real headline-softening defect already covered in §10 — a genuine but different finding.)

No BLOCK this run reflects a fabricated numeric fact or an invented quote — every flagged item traces
either to entity-matching mechanics or to a legitimate, disclosed headline-framing softening.

## 16. Intelligence/Treatment consistency

**One concrete inconsistency found.** Post #2 (Terraria mod): Intelligence's own real-time
recommendation was explicit — *"Не публиковать как полноценную новость без дополнительной проверки"*
("do not publish as a full news item without additional verification") — yet Treatment classified it
`BRIEF` (not `SKIP`) and it was delivered. Contrast with the one real `SKIP` case in this run's own
sample (§8, the neuroscience-AI story), where a similarly negative recommendation *was* honored,
specifically because that case's evidence was *also* independently classified "weak" by the
evidence-completeness/source-reliability inputs `_classify_event_for_router_treatment()` actually
uses. This shows the treatment gate does not parse the Intelligence recommendation text directly —
it only reaches `SKIP` when the recommendation's negativity happens to coincide with an independently
weak evidence/reliability score. When Intelligence says "do not publish" for a reason those specific
inputs don't capture (here: unresolved/materially-softened facts, not source reliability), the
recommendation can be silently overridden. Delivered content itself was not dangerous in this
instance (Copywriting hedged appropriately), but the structural gap is real and reproducible.

## 17. Source-quality observations

4/16 delivered posts (#1, #10, #12, #13) came from Google News aggregator feeds (`Google News RU:
ИИ` / `Google News: Artificial Intelligence`) and every one of their Fact Safety `issues` lists
independently flagged "Отсутствует основной текст публикации" (no article body available) — the
exact impoverished-aggregator-stub pattern Phase 23.1N's own root-cause investigation first
documented. Collected for backlog per the brief's explicit "do not build source enrichment now"
instruction — not fixed.

## 18. Runtime stability

- **1 analysis failure out of 74** (1.4%): a Research-capability structured-output parse failure
  ("structured_output is missing... the §9.1 floor requires an object") on a Hacker News "Show HN"
  post after 3 internal retry attempts, task now permanently `FAILED` (excluded from all future
  `CREATED`-only reselection — will never be retried automatically). A genuine, isolated incident,
  not a cascading one — the worker loop itself continued normally afterward.
- **0 Telegram send failures** across all 16 real sends.
- **0 `retry_number > 0` AI executions** out of 328 total — no provider-level retries needed this run.
- **16–20 of ~486 configured sources fail every single collection cycle**, always the same named set
  (ComfyUI Releases, VentureBeat AI, Tom's Hardware, AnandTech, Android Authority, MacRumors, Windows
  Central, Axios AI, SemiAnalysis, The Register AI, iXBT News, Azure AI Blog, LangChain/LlamaIndex/Replit
  Blogs, plus the already-known dead `M6 Live Validation Source` test fixture) — consistently stale/
  redirecting/403 feed URLs, not transient flakiness (identical failures in all 4 cycles). Handled
  gracefully every time (logged, skipped, cycle continues) — a real source-pack maintenance backlog
  item, not a stability risk.
- No worker crashes, no DB errors, no queue growth signal, no unusual latency observed in the logs.

## 19. Cost

**$0.5313 total** (baseline $8.210489 → final $8.741823), all on model `gpt-5.6-luna`. By capability:
RESEARCH $0.0997, INTELLIGENCE $0.1362, ENGAGEMENT $0.1328, SCORING $0.0548, COPYWRITING $0.0917,
QUALITY (Fact Safety) $0.0161. 26.6% of the $2.00 safety budget used — the cap was never close to
binding.

## 20. Every incident/anomaly

1. The 1 Research-capability failure (§18).
2. The confirmed Zoom duplicate delivery and the near-miss Supermassive Games triple-source cluster
   (§13).
3. The Intelligence/Treatment inconsistency on Post #2 (§16).
4. Two headline-softer-than-source cases (§10).
5. The persistently-broken ~16-20-source subset in the source pack (§18).
6. **Carried forward from Phase 23.1N.1, not a canary-time incident**: starting Docker Desktop to
   bring up Postgres for this canary's own preflight work risks auto-resuming restart-policy
   containers exactly as it did in Phase 23.1N.1 — mitigated this time by never touching Docker again
   after Postgres/Redis were already up from that prior incident's cleanup, but the underlying gap is
   unaddressed. See §23.

None of the above caused a live-safety violation — no wrong destination, no cap breach, no runaway
cost or volume.

## 21. Post-run worker state

At `CANARY_END`, the script's own process exited itself (`exit code 0`, confirmed via the harness's
task-completion notification) — `stop_reason=runtime_reached`. Verified directly afterward:

- `docker ps`: only `ai_newsroom_postgres` (healthy) and `ai_newsroom_redis` (healthy) running —
  identical to the preflight state; nothing else was ever started.
- No stray `python.exe` process remained (confirmed via `Get-Process`).
- No Telegram, backend, automation, content, or news-analysis worker container was ever started for
  this canary.

## 22. Remaining NEWS blockers

1. **No live cross-source semantic duplicate detection** (`story_memory_mode=off`) — directly
   responsible for the confirmed Zoom duplicate and the near-miss Supermassive Games cluster (§13).
   This is the single most consequential finding of this canary.
2. **Intelligence recommendation is not a hard gate** — Treatment only reaches `SKIP` when a negative
   recommendation happens to coincide with independently-weak evidence/reliability scores, not from
   the recommendation text itself (§16).
3. **Recall gap under real cadence**: with `content_generation_poll_interval_seconds=1800` and
   `content_generation_batch_size=5`, up to 5 genuinely eligible, correctly-scored stories can sit
   unprocessed for up to 30 minutes at a time, and any still queued when a bounded run ends are never
   delivered at all (12 such cases this run, §8) — not a defect in a 24/7 deployment (where the queue
   never "ends"), but worth noting if VPS cadence tuning is ever revisited.
4. Two headline-softer-than-source language cases (§10) — not blocking, human-review material.
5. Persistently broken subset of the source pack (§18) — maintenance backlog, not a NEWS blocker.

None of these are regressions from Phase 23.1N.1's own image-ranking work, which itself showed zero
issues this run (§14).

## 23. VPS readiness

Carrying forward Phase 23.1N.1's own operational finding, now reinforced by this run's own
experience of starting Docker Desktop for preflight purposes: **Docker restart policies must be
explicitly reviewed before Phase 23.2**, specifically:

- Docker restart policies (which services get `restart: unless-stopped` vs. a manual/health-gated
  start)
- Startup ordering (Postgres/Redis must be healthy before any application service attempts to
  connect)
- DB readiness and Redis readiness checks before application services accept work
- Application (worker/bot/backend) startup sequencing, so a bare daemon or VPS reboot cannot
  silently resume live processing before configuration/readiness checks pass — the exact failure
  mode Phase 23.1N.1 hit by accident and this canary deliberately avoided by never restarting Docker
  mid-run.

This is a deployment-design item for Phase 23.2, not something this canary attempted to solve.

## 24. Recommendation: **B — SMALL FIX REQUIRED BEFORE VPS**

The pipeline is fundamentally sound at 24/7-representative volume: no runaway publishing (16/20 cap,
never close), no unsafe routing (0/16 sends anywhere but the approved destination), acceptable
Russian (2 minor headline-softening cases out of 16, no calques), acceptable brevity (16/16 exactly
one paragraph, no padding), story-led news preserved where applicable (2/2 clean), image quality
strong (9/9 real images all correctly on-domain, 7/7 no-image cases correctly had no candidates),
source buttons correct (16/16), no systemic factual hallucination pattern (3 BLOCKs, 2 likely false
positives, 1 genuinely uncertain — none fabricated), runtime stable (1 isolated failure in 74, zero
retries, zero crashes), and costs well bounded ($0.53 of $2.00).

However, this canary's larger, longer, more representative sample directly surfaced a real, concrete,
reproducible problem a smaller sample never had the volume to catch: **running 24/7 with
`story_memory_mode=off` will predictably publish duplicate/near-duplicate coverage of the same
real-world story from different outlets** — not hypothetically, but confirmed once (the Zoom case)
and nearly a second time (Supermassive Games) inside a single 2-hour window. This, plus the
Intelligence/Treatment consistency gap (§16), are exactly the class of "small, evidence-backed fix"
this decision option describes — neither is safe to wave through into unattended 24/7 operation
without addressing at least the duplicate-detection gap first (enabling `story_memory_mode=shadow`
with a real bake period would be the natural, already-accepted-in-principle next step, consistent
with this project's own established shadow-before-enforce convention — a decision for human review,
not made here).

## STRICT STOP

Canary complete, workers verified stopped, review packet and this report written. No VPS action, no
`.env` changes, no enforce modes enabled, no editorial fixes applied based on this canary's findings,
no Phase 23.1O follow-on work performed automatically. Awaiting human review.
