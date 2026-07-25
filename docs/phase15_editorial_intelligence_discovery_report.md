# Phase 15 — Editorial Intelligence — M0 Discovery Report

Status: DISCOVERY ONLY. No code, `.env`, container, migration, or workflow changes were made while
producing this report. Phase 14.5 Observation Mode was not touched, stopped, or modified.

---

## 1. Current-state architecture map (relevant to Phase 15)

```
Sources (config/newsroom_sources_v1/sources/*.yaml)
  -> Collector (services/collector.py)
       -> services/cleaning.py (title/whitespace/length cleanup, dedup hash)
       -> services/deduplication.py (exact source_id+external_id match)
       -> NewsEvent (database/models/news_event.py)  [category hardcoded UNKNOWN here]
  -> Triage (services/triage.py, services/triage_orchestrator.py)
       -> deterministic combined_score = 0.6*freshness + 0.4*reliability -> TaskPriority
       -> EditorialTask (database/models/editorial_task.py), type=NEWS_ANALYSIS
  -> WorkflowRunner (workflows/runner.py) executes workflows/definitions/news_analysis.py:
       research -> intelligence -> engagement_analysis -> scoring   (4 LLM calls, capabilities/*)
       -> results land only in EditorialTask.workflow (JSON step_results); NewsEvent unchanged
  -> scripts/run_content_generation.py selects eligible events (score gate, freshness, dedup by
     event_id) and creates a NEW EditorialTask, type=CONTENT_GENERATION, fresh empty step_results
       -> workflows/definitions/content_generation.py:
          research -> intelligence -> copywriting -> quality   (4 more LLM calls, re-derives
          research/intelligence from scratch — no reuse of NEWS_ANALYSIS's output)
       -> ContentDraft (database/models/content_draft.py)
  -> services/editorial_inbox_service.py / services/telegram_notifier.py
       -> bot/formatting.py: render_editorial_card() -> Telegram Editorial Inbox (private chat only)
```

Each capability (`capabilities/research_capability.py`, `intelligence_capability.py`,
`engagement_capability.py`, `scoring_capability.py`, `copywriting_capability.py`,
`quality_capability.py`) is a single-shot LLM call via `capabilities/gateway_call.py:call_generate()`
against the LLM Gateway (`integrations/llm_gateway/`). Only `ScoringCapability` retries (once, on
schema-validation mismatch).

---

## 2. Root cause of malformed titles (Part 1)

**Confirmed root cause**: `integrations/sources/rss_source.py:47` —
`text = entry.get("summary") or entry.get("title")` — the feed's summary/description is preferred
over the clean `<title>` element, and neither is HTML-stripped or entity-unescaped anywhere in the
pipeline before it becomes `RawNewsItem.text`. `services/cleaning.py:_extract_title` (lines 57-65)
then takes the first line of that raw text and only trims whitespace/length — no tag stripping, no
entity unescaping.

- **Google News feeds** (`google_news_ai`, `google_news_ru_ai`, `config/newsroom_sources_v1/sources/trends.yaml:89-108`, `type: rss`): Google News RSS `<description>` starts with an `<a href=...>`
  anchor wrapping the real headline. Because `summary` wins over `title`, and the anchor is on the
  first line, `_extract_title` returns literally `'<a'`.
- **llama.cpp Releases** (`config/newsroom_sources_v1/sources/github.yaml:153-157`, `type: atom`,
  GitHub's `releases.atom`): GitHub's Atom `<summary>` for a release is markdown-rendered HTML,
  often starting with `<img>`/`<p>`. This source is configured as a plain Atom feed and routed
  through the same broken `RSSSourceAdapter` path — it is **not** using the clean, JSON-based
  `GitHubSourceAdapter` (`integrations/sources/github_source.py:197-218`), which extracts
  title/body correctly and is unaffected.
- Both `atom` and `rss` source-definition types map to the identical `RSSSourceAdapter`
  (`services/adapter_keys.py:49-50`), so any Atom-based source is exposed to the same defect.

**Order relative to dedup**: title extraction happens **before** deduplication. `_process_item`
(`services/collector.py:167-198`) calls `cleaning.clean_item()` first, then computes a content hash
and checks `deduplication.is_duplicate()`. Dedup is exact-match on `(source_id, external_id)` only —
content/title-independent, so malformed titles don't interact with dedup logic.

**A clean title is usually available**: `entry.get("title")` (the actual `<title>` element) is
typically clean plain text for both Google News and the llama.cpp Atom feed — it's used only as a
*fallback* when `summary` is absent, which is backwards for title-extraction purposes.

**Existing precedent already in the codebase**: `integrations/sources/hacker_news_source.py:81,84`
already calls `html.unescape()` on raw titles/text — proof the codebase has a working, tested
pattern for this exact class of problem, simply not applied to `RSSSourceAdapter`. There is no
populated `utils/` module and no `BeautifulSoup`/`bleach`/`html2text` dependency — `html.unescape`
plus a small tag-stripping regex is the natural minimal tool, consistent with existing precedent.

**Test coverage gap**: `tests/test_rss_source.py` only exercises clean, HTML-free bodies — no test
currently exercises HTML-laden titles/summaries. This is an untested gap, not a regression.
`tests/test_hacker_news_source.py:65` does assert `html.unescape` behavior for HN, confirming the
pattern is already validated elsewhere in the test suite.

**Recommended minimal normalization contract** (not implemented):

```
raw title candidate (prefer entry.title; fall back to first line of entry.summary)
  -> html.unescape()
  -> strip HTML tags (small regex, e.g. `<[^>]+>`; no new dependency)
  -> whitespace normalization (already exists downstream, cleaning.py)
  -> validation:
       - empty after cleanup -> drop item (extend the existing None-return pattern in
         clean_item(), which already handles some empty cases but not "became empty after
         tag-stripping")
       - still >50% HTML-tag-like characters after stripping -> drop item (signal of a
         structurally broken source)
       - title is a bare URL -> drop item
       - length cap already exists (TITLE_MAX_LENGTH = 120, cleaning.py:16) -> keep as-is
  -> clean NewsEvent.title
```

Do not invent titles via LLM. If no clean title can be derived, drop the item — consistent with
`clean_item()`'s existing `None`-return-and-skip behavior.

**Safest fix boundary**: `RSSSourceAdapter._to_raw_item` (`rss_source.py`) should pass both
`entry.title` and `entry.summary` through to `RawNewsItem` (today only a merged `text` field is
built), and `services/cleaning.py` (`_extract_title`/`clean_item`) should prefer an explicit title
field when present and non-empty, applying the cleanup/validation contract above. This is the
smallest change that fixes title quality without touching the RSS/Atom adapter's content-body
extraction or the dedup/collector contract.

---

## 3. Root cause of category "UNKNOWN" (Part 2)

**Confirmed root cause**: `NewsEvent.category` is unconditionally set to `EventCategory.UNKNOWN` at
creation time, for every source and every item, and is **never updated by anything downstream**.
`services/collector.py:186` — `NewsEvent(..., category=EventCategory.UNKNOWN, ...)` — this is
explicit and documented in the module's own docstring. This is a known, previously-deferred
architectural gap, not a new bug: `docs/phase9_final_decisions.md:143` and
`docs/phase9_precontract_audit.md:255` both record "per-item category classification — No, always
UNKNOWN" as an explicit Phase 9 decision.

- **Allowed enum values** (`database/models/news_event.py:13-23`): `AI, GADGETS, TECH, STARTUPS,
  SOFTWARE, HARDWARE, CYBERSECURITY, UNKNOWN` (`UNKNOWN` added later via migration
  `8941ebf13fb0_add_unknown_event_category.py`).
- **No LLM currently predicts category.** `IntelligenceCapability`'s output schema
  (`capabilities/intelligence_capability.py:38-44`) is
  `["significance", "angle", "audience_relevance", "recommendation"]` — category is not among the
  outputs. Intelligence only *reads* `news_event.category` as input context; it has no write-back
  mechanism. No other capability (`research`, `scoring`, `copywriting`, `quality`) touches category.
- **Category is carried through verbatim, not lost.** `services/editorial_inbox_service.py:34` and
  `services/telegram_notifier.py:50` both pass `news_category=event.category.value` straight into
  `EditorialInboxCard.news_category` (`schemas/editorial_inbox.py:29`), rendered unmodified at
  `bot/formatting.py:75`. Since the source value is always the literal string `"UNKNOWN"`, that is
  exactly what the Telegram card shows — confirmed live: **100% of observed delivered cards** show
  `UNKNOWN` (`docs/phase14_5_observation_run_report.md:413-414`, all 3 delivered messages in §3 of
  the same report; `docs/phase14_5_real_news_validation_report.md:110,121-123`).

**Recommended smallest fix** (no new taxonomy needed — the existing 7-value enum is already
schema-registered and already flows untouched through `EditorialInboxCard`):

1. **Deterministic, cheapest** (recommended default): derive category from each source's own
   config-level tag/category (`config/newsroom_sources_v1/sources/*.yaml` already tags sources,
   e.g. `category: aggregator`, `tags: [ai, news, aggregation]` — noted as "partially available but
   currently unused" in `docs/phase9_final_decisions.md:141`). Zero new AI calls, deterministic,
   but coarse (source-level, not per-item). **Open question to verify at implementation time**:
   whether these YAML tags are currently persisted onto the `NewsSource` DB row at all, or only
   live in config — this determines whether M2 needs a migration.
2. **LLM-predicted, higher-fidelity, deferred option**: add `category` to `IntelligenceCapability`'s
   output schema (it already receives title + Research's facts) and write the predicted value back
   onto `NewsEvent.category` after the workflow completes. Reuses an existing call (zero new
   provider calls), but requires new write-back plumbing — today **nothing** writes analysis
   outputs back onto `NewsEvent`; all outputs live only in `EditorialTask.workflow` JSON. This is a
   larger, new mechanism and should be considered a stretch goal, not the M2 default.

---

## 4. Current editorial scoring model (Part 3)

**There is no single "editorial score."** Two independent, disconnected scoring mechanisms exist.

### 4a. Triage priority (deterministic, pre-LLM, decides processing order — not a quality score)

`services/triage.py:61-103`, a pure function with zero LLM calls, contractually closed to exactly
two inputs (line 78-83: "no other NewsEvent/NewsSource field may be added to this formula without a
Contract amendment"):

| Signal | Used? | Source field | Weight | Range | Fallback |
|---|---|---|---|---|---|
| Freshness | Yes | `services/freshness.py:compute_freshness().weight` | `FRESHNESS_WEIGHT=0.6` | 0.0-1.0 | uses `collected_at` if `published_at` missing |
| Source authority | Yes | `NewsSource.reliability_score` (nullable) | `RELIABILITY_WEIGHT=0.4` | ~0.0-1.0 | `DEFAULT_RELIABILITY_SCORE=0.5` if null |
| relevance/novelty/engagement/trend/virality/importance | No | — | — | — | — |

`combined_score = 0.6*freshness + 0.4*reliability` maps to `TaskPriority` via fixed thresholds
(≥0.75→S, ≥0.55→A, ≥0.35→B, else C — `triage.py:44-48`), driving `EditorialTask.priority` and
budget/ordering (`services/budget_guard.py:104`). **Not displayed to editors, not the 0-100 score.**

### 4b. ScoringCapability (LLM, inside NEWS_ANALYSIS, produces the 0-100 "score")

`capabilities/scoring_capability.py`, single LLM call via `prompts/scoring/v2.yaml`. Prompt input
(`_build_request`, lines 129-140) is **only** `news_event.title`, `.category`, `.summary`, and
target language — it does **not** read `context.business.workflow_state.step_results`, so
Research's, Intelligence's, and Engagement's outputs from the same workflow run (executed
immediately before scoring: `workflows/definitions/news_analysis.py:19-24`) are **invisible to
scoring**.

| Signal | Used? | Weight/structure | Notes |
|---|---|---|---|
| relevance/importance/novelty | Folded into one holistic judgment, no separate field | none (LLM holistic) | not structured |
| freshness | No | — | not in scoring's prompt context at all |
| source quality | No | — | — |
| engagement (predicted) | No | — | Engagement step runs right before Scoring in the same workflow and is simply not wired in |
| trend/virality | No | — | — |

Output schema (`prompts/scoring/v2.yaml:17-27`): `{score: integer 0-100, rationale: string}` —
**the entire score is one LLM judgment call, no deterministic sub-formula, no weighted components.**

**Where the score goes**: `NewsEvent` has **no `score` column at all** — the score is persisted only
inside `EditorialTask.workflow` (JSON `step_results`). `workflows/definitions/content_generation.py`
has zero references to `scoring`/`score` — CONTENT_GENERATION never sees NEWS_ANALYSIS's score
directly (it re-derives eligibility via the score-gate query in `scripts/run_content_generation.py`,
not by reading the score at generation time). `bot/formatting.py` never renders a score field — **the
score is computed but never surfaces to the editor** in the Telegram card.

**Confirmed absent** (not assumed): relevance, novelty, trend strength, virality, and
business/editorial importance as distinct structured signals — none exist as separate fields
anywhere in the current scoring path.

---

## 5. Engagement data availability matrix (Part 4)

`capabilities/engagement_capability.py` is a fully implemented LLM capability, but explicitly scoped
to **predicted, not observed**, engagement — its own docstring and `prompts/engagement/v1.yaml:16`
both state no real Telegram/HN metric is available to or consumed by it, and instruct the LLM to
never claim access to real metrics. `_build_request` feeds only title/category + Research's +
Intelligence's outputs — no raw Telegram signal is available at this call site even if desired.

| Signal | Collected today? | Persisted? | Obtainable without architecture change? |
|---|---|---|---|
| Views | No | No | **Yes** — Telethon `Message.views` already available in `TelegramSourceAdapter._to_raw_item` (`telegram_source.py:57-67`), simply not read |
| Forwards | No | No | **Yes** — `Message.forwards` likewise available, not read |
| Replies/comments | No | No | Partial — Telethon exposes `.replies.replies` for channel posts, not read |
| Reactions | No | No | Partial — needs current Telethon reaction API, same client/session, no new integration |
| Channel/subscriber size (reach) | No | No | Requires one additional Telethon call (`get_entity`/`GetFullChannelRequest`) via the existing client — no new integration, but not literally "already fetched" |

`RawNewsItem` is built from only `external_id`, `text`, `url`, `published_at`
(`telegram_source.py:62-67`) — all engagement fields on the Telethon `Message` object are dropped
at this exact adapter boundary before anything downstream ever sees them.

**Source/channel audience metadata**: `NewsSource` (`database/models/news_source.py:23-40`) has
`reliability_score` only — no subscriber-count/audience-size field. `TelegramChannel`
(`database/models/telegram_channel.py:12-28` — the **outbound** delivery-channel model, not an
inbound source) has `telegram_chat_id`, `name`, `description`, `brand_voice_id`, `settings` — no
member/subscriber-count field either. **No audience-size or authority metadata exists in either
model today.**

**Normalization concepts** ("engagement relative to channel size", "velocity over time",
"relative-to-baseline performance"): confirmed absent by grep — these do not exist yet and would be
entirely new if implemented.

---

## 6. Fact-safety gap analysis (Part 6)

Chain: `NewsEvent -> ResearchCapability -> IntelligenceCapability -> CopywritingCapability ->
QualityCapability -> ContentDraft`. Each step is a single-shot LLM call; no external tool/browsing
capability exists anywhere in this chain.

**Evidence each step actually receives**:

| Step | Sees `NewsEvent.content`? | Sees prior step outputs? |
|---|---|---|
| Research | Yes — only step that does | — |
| Intelligence | **No** (explicit code comment: "never `content`, since Intelligence MUST NOT re-extract facts") | Research's `facts`/`confidence`/`gaps` (stringified) |
| Copywriting | **No** | Research's + Intelligence's outputs (stringified verbatim) |
| Quality | **No** (only title/category/summary) | Copywriting's draft (title/body/hashtags) |

**From Copywriting onward, the model never re-sees raw source content** — only Research's own
*summarized, paraphrased* `facts` list. Any hallucination Research's single LLM call introduces
propagates uncaught through Intelligence and Copywriting with no re-grounding step.

- **No external evidence retrieval**: `research_capability.py:9-14` states explicitly that no
  external research/browsing/fact-checking tool exists in this architecture; `GenerateRequest`
  carries no `tools` field.
- **No citation/provenance retention**: output schemas have no citation/source/evidence-id field;
  `facts` is a bare list of strings.
- **Quality's actual check** (`prompts/quality/v3.yaml:16-23`) does instruct the LLM to "flag a
  draft that contradicts, invents, or omits key facts" and "factual-sounding claims with no
  supporting detail" — but it only receives title/category/summary (never `content`, never
  Research's raw facts) and is one non-deterministic judgment call with no explicit claim-by-claim
  checklist to verify against.
- **No existing fact-check capability/schema** exists anywhere (grep confirms only prose comments
  explaining the absence, no implementation).
- **This matches the concrete Phase 14.5 finding**: the validated real draft
  (`docs/phase14_5_real_news_validation_report.md:164-169`) added "Andreessen Horowitz led the
  round" and "Uber is among the investors" — specifics absent from the source `NewsEvent.title` —
  flagged as unverified-but-plausible, not confirmed hallucination, but structurally exactly what
  this gap analysis predicts: Copywriting only ever sees Research's paraphrase, never the source.

**Deterministic claim-support check is feasible and cheap**: entity/keyword-overlap between the
draft body and `title + content + summary` (+ Research's `facts`) can flag *unsupported new
entities* (e.g., an investor name absent from all source text) without any LLM call. This only
verifies presence, not semantic correctness — a reasonable first gate, not a full fact-checker.

**Recommended gate placement**: inside `QualityCapability.execute()`
(`capabilities/quality_capability.py:147-188`), as a deterministic pre/post-check alongside the
existing `_floor_validate()` schema check — same call count, no new step, no new capability. Quality
is the pipeline's designated review point and already reads the full draft.

---

## 7. Cost / latency impact (Part 7)

**Confirmed call count** (each row = one `call_generate()` round-trip to the LLM Gateway):

| Workflow | Steps | Nominal calls | Max calls (w/ retry) |
|---|---|---|---|
| NEWS_ANALYSIS | research, intelligence, engagement_analysis, scoring | 4 | 5 (scoring may retry once on schema mismatch) |
| CONTENT_GENERATION | research, intelligence, copywriting, quality | 4 | 4 (no retries) |
| **Total per delivered story** | | **8** | **9** |

This **confirms** the reported "~8 provider calls" figure, with one correction: only
`ScoringCapability` can exceed its nominal count, so the true worst case is 9, not 8.

**Material inefficiency already present, relevant to Phase 15 cost tradeoffs**: `research` and
`intelligence` run **twice per delivered story** — once in NEWS_ANALYSIS, once again from scratch in
CONTENT_GENERATION — with zero cross-workflow reuse. `step_results` is scoped per-`EditorialTask`,
not per-`NewsEvent` (`workflows/runner.py:141`); `scripts/run_content_generation.py:99-100` creates a
brand-new task with empty `step_results` every time. 4 of the 8 calls are a full, redundant re-run of
steps already computed minutes earlier for the same event. (Observed evidence: these two
re-derived calls returned in ~7ms in the validated real-news run, `docs/phase14_5_real_news_
validation_report.md:48-55` — the gateway's `CacheCoordinator` served them from cache when
prompt/content were identical, partially masking the cost impact but not the redundant call count.)

**Cost is not currently measurable from the database**: `capabilities/executor.py:10-13` states
explicitly that `CapabilityExecutor` **must not** persist any `AIExecution` row and never calls
`CostTracker` (a standing architectural decision, "Amendment B"). `RedisCostTracker` is instantiated
at boot but `.record()` has zero call sites outside tests. This is corroborated live: Observation
Mode's health check (`docs/phase14_5_observation_run_report.md:439-442`) independently found no
real spend figure obtainable from application state.

**Implication for every Phase 15 proposal**: only deterministic, in-process checks (title
normalization, category fallback, deterministic claim-overlap gate) are genuinely zero-call
additions. Any new LLM-judged signal (e.g., a structured novelty/relevance sub-score) should be
folded into an **existing** call's prompt/schema rather than becoming a new capability/step, to
avoid growing the call count past 8 nominal / 9 max.

---

## 8. Observation-mode evidence (Part 8)

Source: `docs/phase14_5_observation_run_report.md` (living document, includes a same-day health
check) and `docs/phase14_5_real_news_validation_report.md`. Not altered; read-only.

### CONFIRMED

- **Malformed HTML-fragment titles reach the live pipeline on an ongoing basis** — Google News (×3
  in one snapshot), llama.cpp Releases (×2), Lobsters, Techmeme, 9to5Mac, 9to5Google all produced
  raw-HTML titles in a single 10-item recent sample (6 of the latest 10 events malformed).
- **Malformed titles usually — but not always — score near 0.** The scoring capability evidently
  scores on more than the raw title field: one Techmeme event (`f0a32409`, title literally
  `'<a href="https://techcrunch.com/...">...'`) scored **78** and **was delivered to a real Telegram
  message with the broken HTML header rendered verbatim**. This is a real, live editorial-quality
  defect, and it is direct evidence that **relying on the LLM score alone to filter malformed titles
  is not reliable** — a deterministic hard gate is needed (see Part 5 design below).
- **Category renders literal "UNKNOWN" on every single delivered card observed** — 3 for 3 in the
  cumulative delivered-message count, consistent with the root cause in §3.
- **Duplicate NEWS_ANALYSIS tasks**: 108 distinct events have 2-3 separate `NEWS_ANALYSIS`
  `EditorialTask` rows (confirmed via `GROUP BY event_id HAVING COUNT(*) > 1`), caused by
  active-only dedup in task creation (not full-history dedup). Real cost impact: each duplicate
  re-run costs up to 4 additional provider calls. Contained downstream — `CONTENT_GENERATION`'s own
  dedup (by `event_id`, any status) still holds, so no duplicate drafts or Telegram sends resulted.
- **Unverified secondary claims in a generated draft** (Andreessen Horowitz / Uber investor
  specifics not present in the source title) — consistent with, and explained by, the fact-safety
  gap in §6.
- **`CostTracker.record()` is never invoked in real operation** — no dollar figure was obtainable
  from application state during the health check, matching the static code finding in §7.
- **Score distribution is heavily skewed low**: of 135 scored NEWS_ANALYSIS completions in the
  observation window, average score **18.4**, median **8**, only **6 (≈4.4%)** scored ≥65. This is
  strong evidence that most collected news is genuinely low-relevance/low-quality under the current
  single-LLM-judgment scoring, and that the existing `min_score` gate is doing real, necessary work
  — not an arbitrary bottleneck.

### LIKELY

- **The background pipeline is prone to silent, total stalls with no crash/restart signal** — two of
  three workers produced zero cycles for 13+ hours mid-observation, most consistent with a host
  sleep/resume event leaving async/TCP timer state broken for two of three long-lived worker loops.
  This is an operational/infra risk, not a Phase 15 code-scope item, but it is a **live blocking
  dependency for Part 9's M7 live-comparison milestone** — that milestone needs a running pipeline
  and should not be scheduled until pipeline health is independently reconfirmed.

### NOT ENOUGH DATA YET

- **True hallucination/unsupported-claim rate**: only one generated draft has been manually
  reviewed for this; not enough volume to state a frequency.
- **Whether the Techmeme high-score-despite-malformed-title case is a one-off or a recurring
  pattern**: only one confirmed instance observed so far.
- **Real-engagement-based scoring impact**: the feature doesn't exist yet, so there is no data to
  evaluate it against.

---

## 9. Risks and unknowns

- **Whether source YAML tags/categories are persisted onto `NewsSource` DB rows or only exist in
  config** — determines whether the M2 category fix needs a migration. Must be verified during
  implementation, not assumed (flagged in §3).
- **Pipeline health is currently uncertain** — the most recent entry in
  `docs/phase14_5_observation_run_report.md` is a health check with final verdict "C. BROKEN" (two
  of three workers silently stalled). This must be independently reconfirmed (read-only) before
  relying on live data for any Phase 15 milestone, and is a prerequisite the user should be made
  aware of separately from this discovery task's own read-only scope.
- **No historical score/engagement/delivery outcome data exists to calibrate weights against** —
  Scoring V2 weights (§ implementation plan) are proposed from editorial reasoning, not fitted to
  data, because no feedback loop or persisted outcome data currently exists. Weights should be
  implemented as configurable, not hardcoded, so they can be tuned during M7.
- **Telethon-based engagement capture (views/forwards/reactions/reach) has only been confirmed
  available at the API-surface level (Telethon `Message` attributes)** — reliability of `.reactions`
  population across arbitrary channels/permissions was not independently verified against live data
  in this discovery pass and should be spot-checked early in M3, before schema/migration design is
  finalized.
- **Scoring V2's structured schema change and Fact Safety's new schema field both touch prompt
  schemas already under OpenAI strict-schema-compliance testing**
  (`tests/test_openai_strict_schema_compliance.py`) — any new/changed field must satisfy strict
  mode (`additionalProperties: false`, all fields required) established by the existing `v2.yaml`
  scoring prompt's own upgrade from `v1`.

---

PHASE 15 M0 DISCOVERY — SECTIONS 1-9 COMPLETE
