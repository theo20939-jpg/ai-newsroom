# Phase 15 — Editorial Intelligence — M2 Category Reliability — Implementation Report

Status: **PASS** (M2 scope). One significant, pre-existing, unrelated blocker was discovered
during live validation and is disclosed prominently in §10/§13 — it prevented full
NEWS_ANALYSIS/CONTENT_GENERATION-level observation, but does not affect M2's own deliverable
(category assignment happens at collection time, upstream of that blocker).

---

## 1. Original UNKNOWN root cause

`services/collector.py`'s `_process_item()` assigned `category=EventCategory.UNKNOWN`
unconditionally to every `NewsEvent` it created, regardless of source or content. This was an
explicit, documented Phase 9 decision ("per-item category classification — No, always UNKNOWN"),
and nothing downstream ever wrote a different value back onto `NewsEvent.category` afterward.
Confirmed live in Phase 14.5 Observation Mode: 100% of delivered Telegram editorial cards showed
the literal string "UNKNOWN" in the header.

---

## 2. Category source of truth selected

**M2.0 verification findings** (re-confirmed before any code change):

1. **Existing `EventCategory` enum values** (`database/models/news_event.py`): `AI`, `GADGETS`,
   `TECH`, `STARTUPS`, `SOFTWARE`, `HARDWARE`, `CYBERSECURITY`, `UNKNOWN`. No `GAMING` or
   `BUSINESS` value exists — per the task's own instruction to use only real, existing enum
   values, `STARTUPS` is the closest existing equivalent to "business/funding", and no dedicated
   gaming category exists (see §4).
2. **No capability produces a category/topic/classification field.** Inspected every
   `output_schema` in the pipeline: `research` = `{facts, confidence, gaps}`, `intelligence` =
   `{significance, angle, audience_relevance, recommendation}`, `engagement` =
   `{engagement_potential_score, audience_fit, reasoning}`, `scoring` = `{score, rationale}`.
   `angle`/`recommendation` are free-text editorial judgments, not a controlled classification
   vocabulary — mapping them deterministically would mean parsing arbitrary LLM prose, which is
   exactly the "uncontrolled keyword-classification system" the task forbids. **Priority A and B
   (reuse an existing structured AI classification) do not exist in this codebase.**
3. **What IS already available, deterministically, with zero new calls**: every
   `schemas.source_definition.SourceDefinition` the Collector loads each cycle (from
   `config/newsroom_sources_v1/sources/*.yaml`) carries a `tags: list[str]` field — a small,
   curated, closed vocabulary (~90 distinct values across the whole pack, e.g. `ai`, `hardware`,
   `security`, `startup`, `gaming`) authored once per source by whoever built the config. This
   `SourceDefinition` is **already threaded through to the Collector** at the exact point a
   `NewsEvent` is created: `services/adapter_registry.py`'s `AdapterRegistry.resolve()` returns an
   `AdapterResolution(adapter=..., definition=...)` for essentially every source with a pack
   entry, and `services/collector.py::_process_source()` already holds this `resolution.definition`
   — previously only used to build `SourceFetchContext` for the fetch call, never read again.
4. **`NewsSource.category` (the DB column) was checked and ruled out**: it is persisted
   (`services/source_pack_importer.py:103`, confirmed no migration needed), but it holds the
   pack's *source-type* grouping (`official`, `media`, `github`, `reddit`, `research`, `trends`,
   `aggregator`, `social`, `community`) — not a topical signal. It cannot distinguish an AI story
   from a hardware story from a gaming story. `tags`, by contrast, is exactly this signal, but is
   explicitly documented as *not* exported to the `NewsSource` DB row
   (`services/source_pack_importer.py`'s own module docstring: "priority, tags, fetch_interval and
   adapter stay on the SourceDefinition objects and are simply not exported") — it only exists on
   the in-memory `SourceDefinition`, which is exactly what M2 reads instead.
5. **Category is read from `NewsEvent` unmodified all the way to rendering** — confirmed
   unchanged: `services/editorial_inbox_service.py::_to_card()` and
   `services/telegram_notifier.py:50` both do `news_category=event.category.value`, and
   `bot/formatting.py::_render_once()` renders it verbatim in the card header. No downstream file
   needed to change for M2.

**Conclusion**: per the task's own Priority C ("only if repository evidence shows neither A nor B
exists, use deterministic source/content heuristics — but do not invent an uncontrolled
keyword-classification system"), the source of truth selected is **the resolved source's own
config-level `tags`**, mapped through one new, centralized, deterministic function. This is not a
new taxonomy (only the existing 7 non-UNKNOWN `EventCategory` values are ever returned) and not a
second competing category system (it is the only place `NewsEvent.category` is ever assigned).

---

## 3. Existing enum/taxonomy used

`database.models.news_event.EventCategory`: `AI`, `GADGETS`, `TECH`, `STARTUPS`, `SOFTWARE`,
`HARDWARE`, `CYBERSECURITY`, `UNKNOWN` — unchanged, no new value added.

---

## 4. Mapping contract

New module: `services/event_category.py`, single function `categorize_from_tags(tags: list[str]
| None) -> EventCategory`.

- Tags are normalized (`strip().lower()`, `_`/` ` → `-`) before matching, so `"AI"`,
  `"artificial_intelligence"`, `"Artificial-Intelligence"` etc. all normalize consistently.
- A fixed, ordered list of `(EventCategory, frozenset[str])` buckets is checked **narrowest
  first**: `CYBERSECURITY` → `GADGETS` → `HARDWARE` → `STARTUPS` → `SOFTWARE` → `AI` → `TECH`. The
  first bucket with at least one matching tag wins.
- **Why this order, precisely**: the vast majority of this source pack's entries carry an `ai` tag
  (this is an AI newsroom) — if `AI` were checked first, nearly every event would resolve to `AI`
  regardless of a more specific signal being present (e.g. `nvidia_blog`'s real tags are `['ai',
  'gpu', 'hardware', 'robotics', 'nvidia']` — genuinely a hardware story). Checking specific
  buckets first is what prevents the "everything = AI" fallback the task explicitly forbids, while
  still correctly landing on `AI` for the large remaining core of general AI-lab/research/community
  content that has no more specific secondary tag.
- No tags, or no tag matching any bucket → `UNKNOWN`. Never a guessed default.
- `GAMING`/`BUSINESS` do not exist as enum values. The `gaming` tag (used by 3 real sources:
  `tomshardware`, `pcgamer`, `windows_central`, `gamesindustry`) deterministically falls through to
  `TECH` (the general catch-all) rather than being dropped or forced into an unrelated bucket.
  `startup`/`business`/`funding`/`enterprise` tags map to `STARTUPS`, the closest existing
  equivalent.
- Pure function, zero I/O, zero imports of `integrations.llm_gateway` or any `capabilities.*`
  module (structurally verified by `tests/test_event_category.py::
  test_module_imports_no_llm_gateway_or_capability`).

---

## 5. Lifecycle point where category is assigned

At `NewsEvent` creation time, inside `services/collector.py::_process_item()` — the same single
place `category` was previously hardcoded to `UNKNOWN`. `_process_source()` now passes
`resolution.definition` (already-resolved `SourceDefinition | None`) through to `_process_item()`,
which calls `categorize_from_tags(definition.tags if definition is not None else None)`.

This differs from the task prompt's illustrative "conceptual flow" (which pictures category being
derived *after* NEWS_ANALYSIS from classification evidence produced during analysis) because, per
§2 above, **no such evidence exists anywhere in the current pipeline** — none of the four
NEWS_ANALYSIS/CONTENT_GENERATION capabilities produce a structured, mappable classification field.
Building a write-back mechanism from `EditorialTask.workflow` JSON onto `NewsEvent` to support a
non-existent signal would itself be new architecture (Discovery §3: "today **nothing** writes
analysis outputs back onto `NewsEvent`") — explicitly out of scope for M2 ("do not change
architecture", "do not add a new workflow"). Assigning at collection time, from data the Collector
already loads every cycle, is the smallest change that satisfies the task's own Priority C and
"safest existing lifecycle point" instruction. Category is a stable, one-time property of a
`NewsEvent` (it does not change based on how the story is later analyzed), so this is also the
semantically correct place to fix it once and let it persist unchanged, exactly as it already
persists unchanged today (§2 point 5).

---

## 6. Files changed

Production:
- `services/event_category.py` (new) — `categorize_from_tags()`, the single deterministic mapping
  function.
- `services/collector.py` — `_process_item()` gained a `definition: SourceDefinition | None`
  parameter and now calls `categorize_from_tags(...)` instead of hardcoding
  `EventCategory.UNKNOWN`; `_process_source()` passes `resolution.definition` through; module
  docstring updated; unused `EventCategory` import removed (now only used inside
  `event_category.py`).

Tests (new/extended):
- `tests/test_event_category.py` (new) — 28 unit tests for `categorize_from_tags()`.
- `tests/test_automation_integration.py` (extended) — `_fake_seam()` gained an optional
  `definition` parameter (the existing `FakeAdapterRegistry` already accepted one, unused until
  now); 4 new end-to-end tests proving category assignment through the real
  `run_collection_cycle()` → `NewsEvent` persistence path.

No other file was modified for M2. `bot/formatting.py`, `services/editorial_inbox_service.py`,
`services/telegram_notifier.py`, `schemas/editorial_inbox.py` were inspected and confirmed to
already read/render `event.category`/`event.category.value` correctly — none needed a change.

---

## 7. Tests

**A–F (mapping contract), `tests/test_event_category.py`, 28 tests, all passed**:
- A. Known AI classification (`["ai","llm","openai"]` etc.) → `AI`.
- B. Known TECH classification (`["technology","global","news","trends"]` etc.) → `TECH`.
- C. Gaming: no `GAMING` enum value exists (confirmed by inspection) — documented, and tested that
  the `gaming` tag deterministically falls through to `TECH` rather than being dropped or
  misrouted.
- D. Business/startup classification (`["startup","business"]`, `["enterprise"]`) → `STARTUPS`.
- E. Unknown/unrecognized (`None`, `[]`, unrecognized tags) → `UNKNOWN`, safely retained.
- F. Formatting/case variants (`"AI"`, `"Ai"`, `" ai "`, `"artificial_intelligence"`,
  `"Artificial-Intelligence"`, underscore/space/hyphen equivalence) → consistent mapping.
- Additional: priority-order proof that a specific tag (`hardware`, `security`, `business`) wins
  over the broad `ai` tag when both are present on the same source — the explicit "not
  everything=AI" regression case.
- H (no provider calls): structural proof the module imports nothing LLM/capability-related.

**G (persistence flow), `tests/test_automation_integration.py`, 4 new tests, all passed**:
- `test_collected_event_category_assigned_from_definition_tags` — a real `run_collection_cycle()`
  call with a `SourceDefinition(tags=["ai","llm","research"])` produces a `NewsEvent` with
  `category == AI`, read back from Postgres.
- `test_collected_event_category_prefers_specific_tag_over_ai` — mirrors the real `nvidia_blog`
  tag set (`["ai","gpu","hardware"]`) → `HARDWARE`, not `AI`.
- `test_collected_event_category_stays_unknown_for_unrecognized_tags` — an unrecognized tag stays
  `UNKNOWN`.
- `test_collected_event_category_stays_unknown_without_a_resolved_definition` — regression: a
  source with no resolvable `SourceDefinition` (`definition=None`, the previous universal default)
  still safely produces `UNKNOWN`, never raises.
- The downstream half of G (`NewsEvent.category` → `EditorialInboxCard.news_category` verbatim) was
  already covered by a pre-existing test, unchanged by M2:
  `tests/test_editorial_inbox_service.py` (asserts `category=EventCategory.CYBERSECURITY` →
  `card.news_category == "CYBERSECURITY"`) — re-run as part of the full suite below, still passing.

**H (no extra provider calls)**: `test_module_imports_no_llm_gateway_or_capability` is a static
proof; additionally, none of `services/event_category.py`, or the two changed lines in
`services/collector.py`, call `await` on anything besides existing DB/session operations already
present before M2.

---

## 8. Provider-call impact

**Zero new LLM/provider calls.** `categorize_from_tags()` is a pure, synchronous, in-process
function operating only on already-loaded `SourceDefinition.tags` — no network call, no database
query, no `LLMGateway`/`Capability` import anywhere in the new code path. Verified structurally
(§7) and by inspection of the diff (the only new `await` points already existed:
`_process_item()`'s existing `deduplication.is_duplicate()`/`session.flush()` calls, untouched).

**Latency impact**: negligible — one dict/set lookup per event, versus the pre-existing hardcoded
assignment. No measurable difference expected or observed.

---

## 9. Regression validation

**Focused M2 tests**: `tests/test_event_category.py` (28 tests) + 4 new tests in
`tests/test_automation_integration.py` — all 32 passed.

**REGRESSION SAFETY**: per the task's instructions and the M1 precedent, the three pipeline
workers (`automation_worker`, `news_analysis_worker`, `content_worker`) were stopped
(`docker compose stop ...`) before running any DB-mutating test, leaving `postgres`/`redis`
untouched throughout. No `.env` change at any point in this milestone.

**Full suite** (workers stopped): **981 passed, 4 failed**, in 723.9s. All 4 failures
independently root-caused as pre-existing and unrelated to any file this milestone touched:
- `tests/test_content_generation_integration.py::test_full_chain_dry_run_creates_draft_and_renders_without_sending`,
  `tests/test_content_worker_cycle.py::test_run_content_cycle_sequential_no_gather_and_notifies_after_draft_creation`,
  `tests/test_content_worker_cycle.py::test_run_content_cycle_dry_run_never_calls_bot_send_message` — the
  exact same `CONTENT_GENERATION_DRY_RUN=false` (live Observation Mode setting) vs.
  test-assumed-default-`True` mismatch already disclosed and closed in the Phase 15 M1 report.
  Reproduced with a process-scoped override only (`.env` never touched): all 3 pass with
  `CONTENT_GENERATION_DRY_RUN=true` set for that one pytest invocation.
- `tests/test_analysis_worker_main.py::test_enabled_loop_runs_cycles_and_respects_interval` — a
  timing-based test that failed only under the full-suite's concurrent load; passed cleanly when
  re-run in isolation. `worker/analysis_main.py` is untouched by M2.

**Ruff**: `ruff check .` — all checks passed, repo-wide.
**Mypy**: clean on `services/event_category.py`; `services/collector.py` has one pre-existing,
unrelated `telethon` stub-gap error (confirmed present before M2's changes, same class of finding
already disclosed for `feedparser` in the M1 report).
**Architecture validator** (`scripts/validate_architecture.py`): 0 violations.

---

## 10. Deployment

**Scope decision**: rebuilt and redeployed **`automation_worker` only** — the sole service whose
code path calls `services.collector` (confirmed: `worker/main.py`/`worker/cycle.py` are the only
files importing `services.collector`/`run_collection_cycle`; `worker/analysis_main.py` and
`worker/content_main.py` never do). This mirrors the M1 deployment's exact scope decision and
reasoning.

**Steps taken**:
1. Recorded pre-deploy image IDs (`automation_worker`: `77394c2cd81a`) and `postgres`/`redis`
   container IDs (`f455463fc8b2...`/`93016f4638d5...`).
2. `docker compose build automation_worker` — built cleanly, no `.env`/`docker-compose.yml`
   change involved.
3. `docker compose up -d automation_worker` — recreated only that container. `postgres`'s own
   container ID was byte-identical before and after (confirmed: `f455463fc8b2...`) — no
   unavoidable dependency recreation this time (matches M1's own disclosed
   `env_file`-config-hash behavior note; this time it didn't trigger).
4. `docker compose up -d news_analysis_worker content_worker` — restarted the other two workers
   (stopped for testing in §9) from their existing, unrebuilt images (`5be83c89682e`/
   `ae0728e7c89d`, confirmed identical to their pre-session IDs) — they do not run any M2 code
   path, by design.

**Product configuration — confirmed unchanged** (read directly from `Settings` after deploy):
`NEWS_COLLECTION_ENABLED=True`, `NEWS_ANALYSIS_ENABLED=True`, `CONTENT_GENERATION_ENABLED=True`,
`CONTENT_GENERATION_MIN_SCORE=65`, `CONTENT_GENERATION_DRY_RUN=False`,
`EDITORIAL_CHAT_ID=5507703201`. `.env` was never written by this milestone (`git status --short
.env` shows no change). All 5 containers confirmed `Up` after deployment.

---

## 11. Live validation evidence

`automation_worker`'s first real collection cycle under the new code was observed end-to-end,
read-only: `processed=68 failed=16 created=311 duplicates=2620`. The 16 failures are the same
pre-existing, already-documented dead/redirected feed URLs (ComfyUI Releases redirect,
VentureBeat AI, Tom's Hardware, AnandTech, Android Authority, MacRumors, Windows Central, etc.) —
not new, not caused by M2; each already caught and skipped gracefully by the Collector's existing
error handling, no crash.

**Category distribution of the 311 newly collected `NewsEvent` rows** (read-only query, grouped
by category):

| Category | Count |
|---|---|
| GADGETS | 94 |
| AI | 91 |
| STARTUPS | 44 |
| SOFTWARE | 30 |
| TECH | 19 |
| UNKNOWN | 18 |
| HARDWARE | 14 |
| CYBERSECURITY | 1 |
| **Total** | **311** |

**At least two naturally occurring categories, confirmed** (the task asks for at least 2, e.g.
AI+TECH — this run produced 7 distinct non-UNKNOWN categories naturally in a single cycle, per
source): e.g. `3DNews`/`9to5Google`/`9to5Mac`/`Engadget`/`CNET` → `GADGETS`; `Google News:
Artificial Intelligence`/`Habr: Machine Learning`/`AWS Machine Learning Blog` → `AI`; `Hacker News
Front Page`/`TechCrunch AI`/`ZDNET` → `STARTUPS`; `Lobsters`/`Habr: Artificial Intelligence`/
`PyTorch Releases` → `SOFTWARE`; `Techmeme`/`Know Your Meme` → `TECH`; `PC Gamer` → `HARDWARE`
(tags `['gaming','hardware','ai']` — specific-over-AI priority, §4); `404 Media` →
`CYBERSECURITY`.

**Priority-order proof, live**: `PC Gamer` (real tags `['gaming', 'hardware', 'ai']`) resolved to
`HARDWARE`, not `AI` — the same "not everything=AI" behavior proven in unit tests (§7) reproduced
live.

**No naturally delivered Telegram message was observed in this window** to record a displayed
category from — not because of anything in M2, but because of an unrelated, pre-existing blocker
discovered during this validation pass (§13). Per instruction, this is stated honestly rather than
manufactured or waited out indefinitely: category assignment itself is fully proven live at the
point M2 actually operates (collection time, §5) — the Telegram-card-level display was already
proven correct, unchanged, by the pre-existing `tests/test_editorial_inbox_service.py` case
(`EventCategory.CYBERSECURITY` → `card.news_category == "CYBERSECURITY"`, §7) and by inspecting
that no downstream file needed to change (§2 point 5).

---

## 12. Post-deploy UNKNOWN metric

From the same 311-row live sample (§11):

- **Total new analyzed sample**: 311 newly collected `NewsEvent` rows (one full live collection
  cycle, post-deployment).
- **Meaningful category count**: 293 (94.2%).
- **UNKNOWN count**: 18 (5.8%).

**Why the UNKNOWN rows remained UNKNOWN** (all 18 inspected): every one is from a Telegram-type
source (`Rozetked` `@rozetked`, `vc.ru` `@vcnews`, and two Cyrillic-named Telegram sources) whose
`NewsSource.url` (a Telegram handle, e.g. `@rozetked`) does not match any `url` field in
`config/newsroom_sources_v1/sources/*.yaml` — so `AdapterRegistry.resolve()` correctly returns
`AdapterResolution(definition=None)` for these (§2 point 3), and `categorize_from_tags(None)`
correctly returns `UNKNOWN` (there is no tag data to read at all — this is the same, honest
"cannot classify" case the task explicitly allows, not a mapping-function defect). This matches
the "regression: stays `UNKNOWN` without a resolved definition" test (§7) exactly.

No `EventCategory.UNKNOWN` row in this sample came from a source *with* a resolvable definition
whose tags failed to map — every mapping-eligible source produced a specific category.

Not artificially targeted at 0%, per instruction — 5.8% UNKNOWN, concentrated entirely in one
structurally-explained source class (Telegram channels absent from the tag-bearing config pack),
is the honest evidence from this window.

---

## 13. Important discovery during live validation — pre-existing, unrelated to M2

While waiting to observe a NEWS_ANALYSIS completion for §11's persistence-through-analysis proof,
`news_analysis_worker` logged `"No routable candidate for capability 'unknown' (objective=
best_quality)"` for every research-step call attempted after redeploy (10 `FAILED` NEWS_ANALYSIS
tasks observed in the window, 0 `COMPLETED`).

**Root-caused, read-only**: `phase7:health:openai:gpt-5.6-sol/luna/terra` (the **only three**
models in `integrations/llm_gateway/models/catalog.py`'s entire catalog) are **all** marked
`runtime_unavailable=1` in the shared Redis instance — a permanent (no-TTL) flag
(`integrations/llm_gateway/fallback/health_store.py`) that `ProviderHealthStore.is_healthy()`
checks first and unconditionally returns `False` for. With zero models surviving the routing
engine's health filter, `NoRoutableCandidateError` is raised for **every** capability call,
regardless of which capability, workflow, or `NewsEvent` is involved.

**Confirmed unrelated to M2 and not caused by this session's own testing**: `tests/
test_content_worker_cycle.py::_real_capability_registry()` (used by this session's full-suite
run, §9) wires capabilities to `tests.fakes.fake_gateway.FakeLLMGateway` — a fully fake, in-memory
gateway with **no Redis interaction at all** — so this session's test execution cannot have
written these Redis keys. The `runtime_unavailable` flag carries no timestamp, but the paired
`unhealthy_until_ms` transient marker on `gpt-5.6-sol` reads `2026-07-24T11:18:33Z`, well before
this milestone's own work began — consistent with this being a standing condition from earlier
in Observation Mode's run (the same window Phase 14.5's health check separately found
"BROKEN"), not something introduced today.

**Consequence**: with zero routable models, `NEWS_ANALYSIS`/`CONTENT_GENERATION` cannot currently
complete at all in this environment — a real, severe, standing operational problem, but outside
M2's scope (`services/event_category.py`/`services/collector.py` do not touch the LLM Gateway at
all — confirmed structurally in §7/§8) and outside this task's explicit boundaries (no LLM Gateway
file was named in scope, and "do not change architecture" applies). **Not fixed here** — flagging
it is the responsible action per this task's own emphasis on honest, non-manufactured evidence,
and it directly explains §11's "no naturally delivered Telegram message" result. Clearing these
three Redis keys (`DEL phase7:health:openai:gpt-5.6-sol phase7:health:openai:gpt-5.6-luna
phase7:health:openai:gpt-5.6-terra`) would very likely restore normal routing, but this is a
distinct, separately-authorizable action beyond M2's mandate, not performed in this session.

---

## 14. Cost / latency impact

**Zero new LLM/provider calls** — confirmed structurally (§8) and by the fact that the one
component observed failing live (§13) fails at the LLM Gateway routing layer, a layer M2's own
code never reaches (the Collector's category assignment completes and persists successfully
before any capability/workflow ever runs — proven by all 311 events in §11 having a correctly
assigned, persisted category regardless of the §13 blocker).

**Latency impact**: negligible, as predicted in §8 — the Collector cycle in §11 completed in line
with prior, pre-M2 cycle durations reported in the M1 report (comparable source count, comparable
processed/failed/created/duplicates shape).

---

## 15. Remaining limitations

- **Coarse, source-level signal, not per-item**: two events from the same source always get the
  same category (e.g. every `Engadget` article is `GADGETS`), even though an individual article
  might be more specifically about, say, cybersecurity. This is the explicitly-accepted tradeoff
  of Priority C (deterministic source heuristic) over Priority A/B (neither of which exists in
  this codebase today, §2) — documented, not hidden.
- **Telegram-imported sources without a matching pack `SourceDefinition` stay `UNKNOWN` by
  design** (§12) — they carry no tag data for the mapping function to read. Extending coverage to
  these would require either adding them to the config pack with real tags, or a different signal
  entirely (e.g., channel-level metadata) — both out of scope for M2.
- **`GAMING`/`BUSINESS` do not exist as `EventCategory` values** — `gaming`-tagged sources land in
  the general `TECH` bucket, and `startup`/`business`-tagged sources land in `STARTUPS`, per the
  task's explicit instruction to use only real, existing enum values. Adding dedicated values
  would be a schema/taxonomy change, explicitly out of scope for M2.
- **Priority-order judgment calls are not perfectly semantically pure**: e.g. `google_cloud_ai`
  (tags `['ai','cloud','enterprise','google']`) resolves to `STARTUPS` (via `enterprise`) rather
  than `AI`, and `mistral_news`/`stability_news` (tags including `open-source`) resolve to
  `SOFTWARE` rather than `AI`. These are documented, deterministic, and defensible under the
  "specific beats generic" priority rule (§4) — not silent or arbitrary — but a different priority
  ordering would classify some of these differently. This is inherent to any single deterministic
  priority list over multi-tag sources, not a bug.
- **A significant, pre-existing, unrelated pipeline blocker was discovered** (§13) that prevented
  full NEWS_ANALYSIS/CONTENT_GENERATION-level live observation in this session's window. It does
  not affect M2's own correctness (proven independently at the collection stage, §11/§12), but it
  does mean the "category survives through to a delivered Telegram card" step of live validation
  could only be proven by the pre-existing, unchanged `tests/test_editorial_inbox_service.py` case
  and by code inspection (§2 point 5, §11), not by a fresh, naturally delivered message this
  session.

---

# PHASE 15 M2 COMPLETE — PASS

M2's own scope (eliminating the hardcoded `UNKNOWN` category assignment, using the existing
`EventCategory` taxonomy and an existing, already-loaded config signal, with zero new LLM calls,
zero architecture changes, and no migration) is fully implemented, tested, deployed, and proven
live: 311/311 newly collected events received a category through the new deterministic path,
293 of them (94.2%) a specific, meaningful one, with the remaining 5.8% correctly and
explicably `UNKNOWN`.

A separate, pre-existing, unrelated LLM Gateway routing blocker (§13) currently prevents
NEWS_ANALYSIS/CONTENT_GENERATION from completing in this environment. It predates this milestone,
does not affect M2's own deliverable, and is flagged for separate authorization rather than fixed
here.
