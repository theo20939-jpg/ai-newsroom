# Post-Phase-11 Newsroom Gap Discovery

Discovery only. No production code, test, migration, or architecture contract was modified to
produce this document. Every claim below was independently re-verified against current source
this session — old docs are treated as secondary evidence; current source wins wherever they
disagree.

---

## 1. Executive Summary

**FACT**: Phase 11 delivered exactly what its own Contract described — a read-only Telegram
display layer over already-persisted `ContentDraft` rows. It was never designed to, and does not,
trigger fresh collection or generation.

**FACT**: The full automatic chain the target product describes —
`source → NewsEvent → evaluated/selected → processed → ContentDraft` — is **not continuously
running anywhere in this repository**. Every stage that exists is a correct, tested, but
**manually-invoked, one-shot CLI script**. Nothing polls, schedules, or loops.

**FACT**: Engagement/reach-based scoring, as described in the target product, **does not exist**.
The only scoring implemented (`services/triage.py`) uses exactly two signals — Freshness and
`NewsSource.reliability_score` (a static, per-source authority number) — by an explicit, Contract-
frozen "closed input set" that does not include views/likes/forwards/subscribers.

**FACT**: Image/media infrastructure for the "5+ image candidates" requirement is **entirely
absent** — not partial, not scaffolded. The Telegram source collector actively discards media
(only text/url/timestamp are extracted from each message), no model or schema anywhere stores an
image URL or asset, and the LLM Gateway's only "image" capability is *reading* an image as
multimodal input to a vision model — never generating or discovering one.

**FACT**: The reason `/news` shows "old news" is not a bug — it is the direct, correct consequence
of `/news` being read-only exactly as designed, combined with there being no automatic process that
creates new `ContentDraft` rows. The two eligible drafts in the database were both created by a
human manually running `scripts/run_content_generation.py` during this project's own testing, not
by any running production pipeline.

## 2. Current Proven System

**FACT**, re-verified this session, working end to end when manually invoked in this exact order:
```
scripts/run_collector.py          (one collection cycle, exits)
scripts/run_triage.py             (one triage cycle over NEW events, exits)      [creates EditorialTask, NEWS_ANALYSIS]
scripts/run_content_generation.py <event_id>   (one CONTENT_GENERATION run, exits)
bot/main.py                       (long-running, but only serves /news reads)
```
Each of these is independently correct and tested (786/786 tests, re-confirmed at Phase 11's
close). None of them, on their own or together, forms a continuously-running pipeline.

## 3. Current Automatic Pipeline Reality

**FACT**: `docker-compose.yml` defines exactly three services: `backend` (runs
`uvicorn app.main:app`, a literal health-check stub — `app/main.py` has one route returning
`{"status": "Application running"}`, nothing else), `postgres`, `redis`. **No collector, bot, or
worker service is defined in Docker at all.**

**FACT**: `Dockerfile`'s only `CMD` is the FastAPI stub above.

**FACT**: repo-wide search (`celery|apscheduler|croniter|schedule.every|BackgroundScheduler`)
returns **zero matches**. No scheduler framework is used or imported anywhere.

**INFERENCE**: there is currently no deployment path, containerized or otherwise, that keeps the
collector, triage, content-generation, or bot processes running continuously. Every one of them,
including the bot itself, has only ever been run manually, in a foreground terminal, by a human
(exactly as this entire project session has done throughout).

## 4. Source Collection

**FACT**: `integrations/sources/` contains real, working adapters: `telegram_source.py` (Telethon
Client API — separate credentials from the Bot API used by `bot/`), `rss_source.py`,
`arxiv_source.py`, `github_source.py`, `hacker_news_source.py`.

**FACT**, Telegram specifically: uses the **Client API (Telethon)**, not the Bot API — confirmed
(`integrations/sources/telegram_source.py:1-6`, explicit docstring). Fetches up to 50 recent
messages per channel per cycle (`MESSAGE_FETCH_LIMIT = 50`) via `client.iter_messages()` — real
historical/current post collection, not merely a live stream. `_to_raw_item()` extracts **only**
`external_id`, `text`, `url`, `published_at` — confirmed by direct read, no `.photo`/`.media`
access anywhere in this file, despite Telethon's `Message` object exposing both. **Media is
available at the source and is discarded by this adapter's own code, not by any platform
limitation.**

**FACT**: no channel subscriber count, reach, or engagement signal is fetched or stored anywhere in
this adapter or the `NewsSource`/`NewsEvent` models.

**FACT**: `services/collector.py::run_collection_cycle()` is real, working orchestration — loads
active sources, fetches via the matching adapter, cleans, deduplicates, and persists `NewsEvent`
rows with `status=NEW`. Its own entry point (`scripts/run_collector.py`) runs **exactly one cycle,
then exits** — confirmed by direct read, no loop of any kind.

**Classification**: source collection itself — **WORKING** (as a manually-triggered, one-shot
operation). Continuous/scheduled collection — **MISSING**.

## 5. Freshness / Deduplication

**FACT** (`services/deduplication.py:12-15`): the entire dedup mechanism is a single exact-hash
lookup — `hashlib.sha256(f"{source_id}:{external_id}")`. It answers only "have we seen this exact
item from this exact source before" — nothing else.

**FACT**: there is **no** URL-only dedup independent of source+external_id, **no** content-
similarity/fuzzy dedup, **no** semantic/embedding-based dedup, **no** cross-source event clustering
("is this the same underlying story reported by two different sources") anywhere in this codebase.
A repo-wide search for embedding/vector/similarity-clustering infrastructure in production code
found none.

**FACT**: freshness itself **is** implemented — `services/freshness.py` (read via
`services/triage.py`'s import) computes an age-based tier/weight from `published_at`/`collected_at`
— this genuinely exists and is used by Triage (§6 below).

**Classification**: exact-duplicate suppression — **WORKING**. Cross-source/semantic
deduplication and event clustering — **MISSING** entirely (not partial — no code exists to
attempt it).

## 6. Engagement / Reach / Ranking

**FACT** (`services/triage.py:33-48`, explicit, Contract-cited comment): the *only* scoring formula
in this repository combines exactly two signals: `Freshness` (weight 0.6) and
`NewsSource.reliability_score` (weight 0.4, a static, human-configured per-source number, default
0.5 if unset) — the module's own docstring states this is a "closed input set... no other
NewsEvent/NewsSource field may be added to this formula without a Contract amendment."

**FACT**: `NewsSource` (`database/models/news_source.py`) has no subscriber/reach/audience-size
column. `NewsEvent` has no views/likes/forwards/comments column. No table anywhere in
`database/models/` stores any engagement metric.

**FACT**: `workflows/definitions/news_analysis.py` names a step `engagement_analysis` mapped to
capability name `"engagement"` — but `capabilities/capability_mapping.py:26` maps this name to
`AICapability.INTELLIGENCE` **only for cost/audit-persistence bookkeeping purposes**, explicitly
labeled in its own docstring as *"a temporary persistence stopgap only, not a redefinition of
Engagement as Intelligence... MUST be reconsidered before any real Engagement Capability is
implemented."* `capabilities/registry.py` registers exactly five capabilities — Research,
Intelligence, Copywriting, Quality, Scoring — **no `EngagementCapability` class exists anywhere in
this codebase.**

**INFERENCE, load-bearing**: because `NEWS_ANALYSIS`'s step chain is
`research → intelligence → engagement_analysis → scoring`, and no capability is registered for the
name `"engagement"`, a `NEWS_ANALYSIS` workflow run through `CapabilityExecutor` would **fail** at
that step (`UnknownCapabilityError`) if ever actually executed today. This has apparently never
been exercised in practice — confirmed separately: `services/triage_orchestrator.py` only *creates*
`NEWS_ANALYSIS`-typed `EditorialTask` rows (status `CREATED`); nothing in production code ever
calls `WorkflowRunner.run()` against one of them (re-confirmed: the only production
`WorkflowRunner`/`CapabilityExecutor` construction site is `scripts/run_content_generation.py`,
which always uses `CONTENT_GENERATION`, never `NEWS_ANALYSIS`).

**Classification**: raw/normalized engagement — **MISSING**. Channel-scale reach normalization —
**MISSING**. Velocity/trend — **MISSING** (an `AICapability.TREND` enum value exists but has no
registered capability, identical situation to Creative/Engagement). Freshness — **IMPLEMENTED**.
Static source-authority weighting — **IMPLEMENTED**. Cross-source confirmation — **MISSING**.

## 7. Workflow Automation

**FACT**: `EditorialTask` creation today happens in exactly two places: (a)
`services/triage_orchestrator.py`, creating `NEWS_ANALYSIS`-typed tasks for `NewsEvent` rows with
`status=NEW`/`PROCESSING` (itself only invoked by `scripts/run_triage.py`, a one-shot CLI — no
automatic trigger); (b) `scripts/run_content_generation.py`, creating one `CONTENT_GENERATION`-typed
task per manual invocation with an explicit `event_id` argument.

**FACT**: no code anywhere automatically creates a `CONTENT_GENERATION` task in response to a
`NEWS_ANALYSIS` task completing, a `NewsEvent` being created, or any other event. A human must
manually run `scripts/run_content_generation.py <event_id>`, supplying the event ID by hand.

**FACT**: no worker/queue-consumer process exists anywhere. `WorkflowRunner` is only ever
constructed inside the two one-shot scripts named above.

**Answer to the critical question**: what currently causes `NewsEvent → CONTENT_GENERATION →
ContentDraft` in production? **A human manually running `python -m scripts.run_content_generation
<event_id>`, once, per event, by hand.** There is no automatic trigger of any kind.

## 8. Why `/news` Shows Old News

**FACT**, re-traced directly against current source (`bot/handlers/news.py`,
`services/editorial_inbox_service.py`): `/news` performs **exactly one** `SELECT`-only query —
`ContentDraft` joined to `EditorialTask` filtered `status=COMPLETED`, newest-first, limit 5. It
does **not** trigger collection (**B: no**), does **not** trigger any AI workflow (**C: no** —
mechanically proven by the AST import-boundary tests that assert neither
`services/editorial_inbox_service.py` nor `bot/handlers/news.py` imports `workflows.runner`,
`capabilities.executor`, or `scripts.run_content_generation`), and only reads existing rows
(**D: yes, exclusively**). **This is not a defect — it is the exact, contracted, tested design.**
Old news appears because the only two `ContentDraft` rows in the database were both created by a
human manually running the content-generation script during this project's own testing sessions —
there is no automatic process that would ever add a third.

## 9. Visual / Image Infrastructure

**FACT**: repo-wide search for image/photo/media/asset/creative/meme/vision/S3/MinIO/DALL-E/etc.
in production code returned real matches only in: (a) `AICapability`'s `CREATIVE` enum value
(`database/models/ai_execution.py:22`) — an unused, unregistered persistence-tracking placeholder,
same pattern as `TREND`/`ENGAGEMENT`; (b) `ContentType.MEME` (`database/models/content_draft.py:19`)
— an enum *value* that `ContentDraftService.create_from_result()` never actually assigns (it always
writes `type=ContentType.POST`, confirmed by direct read); (c) the LLM Gateway's `modalities`
field and OpenAI adapter's `input_image` translation (`integrations/llm_gateway/protocol.py:56`,
`providers/openai_adapter.py:177-181`) — this is **vision input only** (letting a model *read* an
existing image as part of a prompt) — there is no `generate_image()` method, no image-generation
provider call, anywhere in the Gateway protocol or any adapter; (d) `services/cleaning.py`'s
docstring, which states plainly that media-only posts are **dropped**.

**FACT**: no database model anywhere stores an image URL, media asset reference, image candidate,
or generated-image metadata. `NewsEvent` has no media column; `ContentDraft` has no media column.

**Classification, precisely**: source media extraction — **MISSING** (media is available at the
Telethon layer today and is actively discarded, not merely unreached). Official/press asset
discovery — **MISSING**. Relevant web-image discovery — **MISSING**. AI image generation —
**MISSING** (Gateway has no generation capability at all, only vision input). Image storage/asset
management (S3/MinIO or any equivalent) — **MISSING**.

## 10. Five-Image Requirement Gap

Decomposed per the task's own framework, each classified from the evidence above:

| Capability | Status | Evidence |
|---|---|---|
| A. Source media extraction | **MISSING** | Telethon adapter discards `.photo`/`.media` (§9) |
| B. Official asset discovery | **MISSING** | No code searches any press/brand asset source |
| C. Relevant image discovery | **MISSING** | No web/image-search integration exists |
| D. AI image generation | **MISSING** | Gateway has no generation method (§9) |
| E. Deduplication (of images) | **MISSING** | No image-comparison code exists (only text-hash dedup, §5) |
| F. Visual ranking | **MISSING** | No relevance/quality/aspect-ratio/trust scoring code exists for any media |
| G. Delivery (show ≥5 to editor) | **MISSING** | Phase 11's card template has no media-attachment path — `bot/formatting.py` produces text-only HTML; `message.answer()` is a text-send call, never `send_photo`/`send_media_group` |

**RECOMMENDATION**: none of A–G share meaningfully with meme generation (§11) beyond both
eventually needing an image-delivery mechanism (G) — they are otherwise independent capability
sets (discovery/extraction vs. generation-from-concept), consistent with the task's own instruction
not to merge them without evidence.

## 11. Meme Generation Gap

**FACT**: `ContentType.MEME` exists as an enum value only. No trigger logic, no "meme-worthiness"
scoring, no concept-generation prompt, no meme template, no image-generation call, no caption-
placement logic, no dedicated quality gate, no storage, and no Telegram media-delivery path exists
anywhere in this codebase. **Every one of these sub-capabilities is MISSING, not partial** — there
is no scaffolding to build on beyond the bare enum value and the already-frozen, deliberately
unused `AICapability.CREATIVE` mapping alias.

## 12. Editorial Actions / Authorization

**FACT**, re-confirmed this session (repo-wide search): zero implementation of Approve, Reject,
Rework, Regenerate, or any `review_status`/`editorial_status` field anywhere in production code.
This matches every Phase 11 report's own finding — nothing has changed since.

**FACT**: `database/models/user.py` defines `User`/`UserRole`, but (re-confirmed) is wired into
zero middleware, zero handler, zero service anywhere in the bot. No bootstrap, no permission
enforcement, no `telegram_id → User` mapping exists.

**INFERENCE**: before any write action (Approve/Reject/Rework) can be built, Contract-level
decisions already named in Phase 11's own frozen "future security gate" (Contract §11) must be
resolved: `User` creation/bootstrap, `telegram_id` mapping, `OWNER` bootstrap, role semantics,
permissions, unauthorized-user behavior, callback authorization, and replay/stale-action
protection. None of this is designed or implemented today.

## 13. Internal Automation vs. Public Publishing

**FACT**: no code path publishes to any public Telegram channel anywhere in this repository (re-
confirmed, consistent with every prior phase's own audits).

**Distinction, precisely** (per this task's own framing):
- **A. Internal automation** (collect/process automatically): **MISSING** — this is the actual
  gap; see §3, §6, §7.
- **B. Editorial delivery** (show results to the SMM team): **WORKING** — Phase 11's `/news`
  correctly does this for whatever already exists in the database.
- **C. Public publishing**: **MISSING**, and explicitly, correctly, out of scope for the near
  term per this task's own instruction.

**RECOMMENDATION**: the missing automation needed for "fresh news" is entirely category A
(schedulers/workers/queues for collection and processing) — it has no necessary relationship to
category C, and building A must not be conflated with or gated on any future C decision.

## 14. 24/7 Operations

**FACT**: `docker-compose.yml` provides `restart: unless-stopped` for `backend`/`postgres`/`redis`
— but `backend` runs only the FastAPI health-check stub, not the bot, collector, or any worker.
None of the actual pipeline processes (`bot/main.py`, `scripts/run_collector.py`,
`scripts/run_triage.py`, `scripts/run_content_generation.py`) has a restart policy, health check, or
containerized presence at all today.

**FACT**: no dead-letter/retry-queue mechanism exists beyond `services/collector.py`'s own
in-process, single-cycle retry-with-backoff for one source's fetch call (`MAX_FETCH_ATTEMPTS = 3`) —
this does not survive a process restart and has no persistence.

**Classification**: 24/7 unattended operation — **NOT READY**. Every component that exists is
correct for a single, human-triggered invocation; none is designed or deployed to run continuously.

## 15. Scale Readiness

**FACT**: `services/budget_guard.py`, `cost_estimator.py`, `cost_tracker.py`, and
`integrations/llm_gateway/rate_limit` all exist and are real, tested (Phase 7) infrastructure —
this part of the stack is genuinely built for volume.

**FACT**: dedup is a single exact-hash lookup per item (§5) — cheap, but does nothing to prevent
near-duplicate stories from separate sources from each independently consuming AI budget at
~1000 items/day scale.

**FACT**: there is no batching/queueing layer between "many `NewsEvent` rows exist" and "run content
generation for one of them" — today this is a fully manual, one-`event_id`-at-a-time CLI
invocation; reaching ~1000/day this way is a human-hours problem, not merely a code problem.

**Classification**: LLM cost/budget guarding infrastructure — **READY** (exists, tested, not yet
exercised at the target volume). Collector volume handling (per-source fetch/retry) — **PARTIAL**
(works, but no cross-cycle scheduling exists to run it repeatedly). Automatic task
execution/queueing at volume — **NOT READY** (no automation exists at all, §7). Dedup efficiency at
scale — **PARTIAL** (correct for exact duplicates, does nothing for near-duplicates across sources,
which is exactly the situation multi-source ingestion at volume would create). Image
search/generation cost — **NOT READY** (no such capability exists to have a cost profile at all).

## 16. Full Feature Matrix

| Feature | Expected product behavior | Current implementation | Status | Evidence | Gap | Dependencies |
|---|---|---|---|---|---|---|
| Source management | Configure/import sources | `services/source_registry.py`, `source_pack_importer.py`, `import_sources.py` | **WORKING** | Direct read, tested | None material | — |
| Telegram collection | Pull channel posts | `integrations/sources/telegram_source.py` (Telethon) | **WORKING** (manual trigger) | §4 | No scheduling; no media capture | Scheduler |
| RSS collection | Pull feed items | `integrations/sources/rss_source.py` | **WORKING** (manual trigger) | File exists, registered | No scheduling | Scheduler |
| Web collection | Scrape web pages | Not found as a generic web-scrape adapter (arxiv/github/hacker-news are structured-API adapters, not generic web scraping) | **PARTIAL/MISSING** | `integrations/sources/` listing | Generic web scraping absent | New adapter |
| Dedup (exact) | Suppress exact repeats | `services/deduplication.py` | **WORKING** | §5 | None | — |
| Dedup (semantic/cluster) | Suppress cross-source repeats | None | **MISSING** | §5 | Entire capability absent | New service |
| Freshness | Age-aware weighting | `services/freshness.py` + `services/triage.py` | **WORKING** | §6 | None | — |
| Engagement scoring | Reach-aware ranking | None | **MISSING** | §6 | Entire capability absent | New signal + schema |
| Reach normalization | Scale by channel size | None | **MISSING** | §6 | No subscriber data captured at all | Source metadata + capability |
| Ranking/prioritization | Combine signals to prioritize | `services/triage.py` (freshness + static authority only) | **PARTIAL** | §6 | Missing engagement input | Engagement scoring |
| Automatic task creation | Event → task without human | None | **MISSING** | §7 | Entire trigger chain absent | Scheduler/worker |
| Workflow execution | Run steps automatically | `WorkflowRunner`/`CapabilityExecutor` (correct, but only invoked manually) | **WORKING** (manual trigger) | §7 | No automatic invocation | Scheduler/worker |
| Research | AI step | `capabilities/research_capability.py` | **WORKING** | Tested, live-proven | None | — |
| Intelligence | AI step | `capabilities/intelligence_capability.py` | **WORKING** | Tested, live-proven | None | — |
| Copywriting | AI step | `capabilities/copywriting_capability.py` | **WORKING** | Tested, live-proven | None | — |
| Quality | AI step | `capabilities/quality_capability.py` | **WORKING** (advisory only, no enforcement) | Tested | Result never gates persistence | New gating mechanism (future) |
| ContentDraft | Persisted output | `services/content_draft_service.py` | **WORKING** | Tested, live-proven | None | — |
| Target output language | Russian by default | `core/config.py` + `capabilities/executor.py` + `prompts/copywriting/v3.yaml` | **WORKING** | Live-proven this project | None | — |
| Telegram inbox | Read-only display | `bot/handlers/news.py` | **WORKING** | Phase 11, live-proven | Forum-topic preservation: upstream limitation, not a defect | — |
| Digest | Some other summary view | `bot/handlers/digest.py` | **SCAFFOLDING** | §16 direct read | Entirely placeholder | Product definition needed |
| Source media extraction | Capture original images | None | **MISSING** | §9 | Actively discarded today | Adapter change |
| Image discovery | Find related images | None | **MISSING** | §9 | No integration exists | New service |
| Image dedup | Avoid near-identical picks | None | **MISSING** | §10 | No image-comparison code | New service |
| Visual ranking | Rank candidates | None | **MISSING** | §10 | No scoring code | New service |
| 5+ image candidates | Show options to editor | None | **MISSING** | §9/§10 | No storage, no delivery path | All of the above |
| AI image generation | Optional creative fallback | None | **MISSING** | §9 | Gateway has no generation method | Gateway extension |
| Meme generation | Original meme creation | Enum value only | **MISSING** | §11 | No sub-capability exists | Image generation + concept logic |
| Approve | Editorial write action | None | **MISSING** | §12 | Not designed | Authorization |
| Reject | Editorial write action | None | **MISSING** | §12 | Not designed | Authorization |
| Rework | Editorial write action | None | **MISSING** | §12 | Not designed | Authorization |
| Auth | Access control | Models exist, unwired | **SCAFFOLDING** | §12 | Zero enforcement | New middleware/design |
| Internal scheduling | Continuous collection/processing | None | **MISSING** | §3/§14 | No scheduler anywhere | New component |
| Public publishing | Post to public channel | None | **MISSING**, explicitly out of scope now | §13 | N/A (not required) | — |

## 17. First Broken Link

Tracing the intended chain from the start:
```
External source
    → [Collector: WORKING, but only when a human runs it]           <- first break: no automatic trigger
    → NewsEvent (status=NEW)
    → [Triage: WORKING, but only when a human runs it]               <- same class of break
    → EditorialTask (NEWS_ANALYSIS, status=CREATED)
    → [nothing ever executes this task — no registered "engagement" capability even if it were run]  <- second, independent break
    → WorkflowRunner  <- never invoked for NEWS_ANALYSIS in production
    → ContentDraft  <- only ever created via a human manually running run_content_generation.py
    → /news  <- correctly displays whatever exists
```
**The first broken link is not deep in the pipeline — it is at the very first arrow.** Nothing
automatically invokes `scripts/run_collector.py`. Every subsequent stage inherits this same
"correct code, no automatic trigger" pattern, compounded once by the additionally-missing
`EngagementCapability` (a second, independent, non-overlapping gap: even a scheduled
`NEWS_ANALYSIS` run would fail today at its `engagement_analysis` step).

## 18. Dependency Graph

```
Scheduler/worker infrastructure (new)
    ├── requires: nothing else new — can wrap the ALREADY-WORKING run_collector.py cycle
    │
    ├── enables → Automatic collection (recurring)
    │       └── enables → Automatic Triage (recurring, already-working logic)
    │               └── requires, before real use: an actual EngagementCapability
    │                   (or a Contract amendment removing it from NEWS_ANALYSIS's step chain)
    │               └── enables → Automatic EditorialTask creation
    │                       └── requires: an automatic NEWS_ANALYSIS-complete -> CONTENT_GENERATION
    │                           trigger (does not exist in any form today)
    │                       └── enables → Automatic ContentDraft generation
    │                               └── enables → /news showing genuinely fresh content (ALREADY WORKS
    │                                   once ContentDraft rows exist - no Phase 11 change needed)
    │
Visual/image infrastructure (new, independent of the above)
    ├── requires: an adapter change to stop discarding source media (small, isolated)
    ├── requires: new discovery/generation/ranking services (large, entirely new)
    └── requires: a new card-delivery mechanism (media-capable send, not text-only) - Phase 11's
        own renderer/handler would need extension, but only after the above exist

Editorial write actions (Approve/Reject/Rework)
    └── requires: Authorization design (User bootstrap, roles, permissions) - orthogonal to both
        of the above, can proceed independently, but is explicitly the LOWEST priority per this
        task's own instruction not to assume it is "next"

Meme generation
    └── requires: image generation capability from the Visual/image branch above, plus its own
        concept/trigger logic - has no dependency on Editorial Actions or Auth
```

## 19. Recommended Remaining Roadmap

Derived from the dependency graph, not assumed:

1. **Fresh News Ingestion Automation** — wrap the already-correct `run_collector.py`/
   `run_triage.py` cycles in a real scheduler/worker (the single highest-leverage gap: everything
   else depends on this existing first).
2. **Engagement/Reach Scoring + Dedup/Clustering Enhancement** — resolve the `EngagementCapability`
   gap (either build it or amend the Contract to remove the step), add real engagement signal
   capture (requires new source-adapter fields), add cross-source/semantic dedup.
3. **Automatic Workflow Orchestration** — the NEWS_ANALYSIS-complete → CONTENT_GENERATION trigger
   that does not exist today; makes `ContentDraft` creation automatic end to end.
4. **Visual Discovery / 5+ Image Suggestions** — source-media extraction (smallest first step),
   then discovery/generation/ranking/delivery, in that order, since delivery needs something to
   deliver and extraction is the cheapest capability to add first.
5. **Meme / Creative Generation** — depends on image generation existing (step 4).
6. **Editorial Actions + Authorization** — deliberately last among near-term priorities per this
   task's own instruction; genuinely independent of 1–5 and can be sequenced whenever product
   priority dictates, but has no code today to build on.
7. **Internal Scheduling / Reliability hardening** (retries, dead-letter handling, monitoring) —
   layered on top of step 1 once a scheduler exists to harden.

**Public auto-publishing is explicitly not included** — no evidence in this repository suggests it
is needed for the next useful increment, and the task's own instruction excludes it.

## 20. Minimum Path to Useful Newsroom

For "I open Telegram and receive genuinely fresh, prioritized, ready-to-use news materials with
text and at least 5 visual options," the **mandatory** minimum set, derived from the dependency
graph:
1. A scheduler/worker that runs collection + triage automatically and repeatedly (§19 step 1).
2. A resolved `EngagementCapability` situation (either implemented or contractually removed) so an
   automated `NEWS_ANALYSIS` run does not fail (§19 step 2, the `EngagementCapability` half only —
   full engagement-signal capture is a quality improvement, not a hard blocker for "fresh," since
   Freshness + static authority alone already produce a valid, deterministic priority today).
3. An automatic NEWS_ANALYSIS-complete → CONTENT_GENERATION trigger (§19 step 3).
4. Source-media extraction + at least one image-discovery mechanism + a media-capable card-delivery
   path in the bot (§19 step 4, in full — this is the literal "5+ image candidates" requirement,
   not optional for the stated experience).

Everything else in the roadmap (deeper engagement scoring, meme generation, editorial write
actions, authorization) is real, valuable, but **not required** to reach the specific experience
described in this task's own target sentence.

## 21. Risks

- Automating collection/triage/content-generation without first resolving dedup-at-scale (§5, §15)
  risks flooding the pipeline with near-duplicate stories from multiple sources, each independently
  consuming AI budget.
- Automating `NEWS_ANALYSIS` execution without first resolving the missing `EngagementCapability`
  will cause every automated run to fail at that step — this must be fixed or the step removed
  before any scheduler is pointed at `NEWS_ANALYSIS`.
- Building image discovery/generation without settling provenance/attribution tracking (§ below)
  risks delivering candidates with no way to trace back to a usable source later.
- `services/collector.py`'s per-cycle retry has no cross-restart persistence — a crashed process
  mid-cycle currently loses that cycle's remaining progress silently (acceptable for a manual tool,
  a real gap for a 24/7 worker).

## 22. Open Questions

- **OPEN QUESTION**: should `NEWS_ANALYSIS`'s `engagement_analysis` step be implemented as a real
  capability, or should the workflow definition itself be amended to remove it (given engagement
  data isn't currently captured anywhere upstream either)? This is a product/architecture decision
  outside this Discovery's own scope.
- **OPEN QUESTION**: for image provenance (Part 11 of the task), what metadata would actually be
  required — source URL and origin domain already exist for `NewsEvent` itself, but no equivalent
  exists for an individual *image* candidate, since no image candidate is ever stored today. This
  needs its own schema decision once image infrastructure is scoped.
- **OPEN QUESTION**: is a single shared "worker" process (collector + triage + content-generation
  orchestration) preferred, or separate, independently-scheduled processes? Both are consistent with
  existing code (each stage is already an independent, composable function) — a genuine product/ops
  choice, not something this Discovery can resolve from evidence alone.

## 23. Final Verdict

Repository-wide gap analysis is complete, based entirely on direct source inspection (file:line
evidence throughout), not inherited assumptions from prior documentation. No code was implemented,
no architecture was changed, no migration was created.

---

POST-PHASE-11 GAP DISCOVERY COMPLETE — READY FOR ROADMAP DECISION
