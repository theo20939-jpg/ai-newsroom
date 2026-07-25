# Phase 15 — Editorial Intelligence — M0 Implementation Plan

Status: PLAN ONLY. Nothing in this document has been implemented. See
`docs/phase15_editorial_intelligence_discovery_report.md` for the evidence this plan is built on.

Architectural constraints preserved throughout: LLM Gateway, existing capabilities/workflows,
Pydantic schemas, WorkflowRunner, NewsEvent/EditorialTask/ContentDraft model boundaries, current
worker separation, Telegram editorial-only delivery. No auto-publication, no public-channel
publishing, no image/meme generation, no approval workflows, no new UI, no unrelated refactors.

---

## Editorial Scoring V2 design (Part 5)

### Signals and proposed weights

No historical outcome data exists to fit weights against (§9 of the discovery report), and Triage's
existing 0.6/0.4 freshness/reliability split answers a different question (processing priority, not
editorial quality) — so these weights are **reasoned, not derived**, and must ship as configurable
settings, not constants, so they can be tuned during M7 live validation.

| Signal | Weight | Source | New vs. existing | Reasoning |
|---|---|---|---|---|
| Relevance + importance | 35% | Restructured field(s) on the existing `ScoringCapability` LLM call | Existing call, restructured schema | Most information-dense signal; keep it dominant since it's the only signal reading full topical context |
| Novelty | 15% | New structured field, same existing scoring call | Existing call, restructured schema | Currently entirely absent (confirmed in discovery §4b) — a real gap worth real weight |
| Freshness | 15% | `services/freshness.py:compute_freshness()` | Existing, already deterministic | News value decays fast; already computed and tested elsewhere, just not fed into the 0-100 score |
| Source authority | 10% | `NewsSource.reliability_score` | Existing field | Moderate weight — most sources default to neutral 0.5, so it mostly matters at the tails |
| Engagement (predicted) | 15% | `EngagementCapability`'s existing output, currently computed but **not read by Scoring** (discovery §4b) | Existing call, wiring fix only | Cheapest possible win — the call already runs immediately before scoring in the same workflow and is simply discarded today |
| Trend/velocity | 10% | New deterministic signal (e.g., count of other recent events sharing a normalized topic/keyword window) | New, deterministic | Least certain design; keep weight low until validated; redistribute to other signals if not implemented in M4 |

`freshness` and `source authority` are merged **in Python, deterministically**, after the LLM
returns its structured sub-scores — not inside the LLM prompt — so the formula stays inspectable,
testable without an LLM, and cheap to re-weight.

### Hard rejection gates (separate from scoring, evaluated first)

Per discovery §8, a malformed title reached delivery at score 78 — proof that scoring alone cannot
be trusted to catch structurally broken input. Gates below are deterministic and run **before** any
LLM call, at the earliest point each check's data is available:

| Gate | Boundary | Rationale |
|---|---|---|
| Malformed title (empty / mostly-HTML / bare-URL after M1 cleanup) | `services/cleaning.py`, at ingestion — drop before `NewsEvent` is even created | Cheapest possible point; saves the full 4-8 downstream LLM calls entirely |
| Duplicate `NEWS_ANALYSIS` task for an event that already has one | Task-creation boundary (Triage/`workflow_service.create_task()`'s `_find_active_task()`) | Discovery §8 found 108 events with duplicate tasks — closing the active-only dedup gap is a pure, zero-call cost fix |
| Stale content | Already implemented (`NEWS_ANALYSIS_FRESHNESS_CUTOFF_HOURS`, `CONTENT_GENERATION_FRESHNESS_CUTOFF_HOURS`) | Keep as a hard gate in V2, not folded into soft scoring |
| Synthetic/test source | Source-eligibility query (e.g., exclude `M6 Live Validation Source`-style example.com entries) | Cheap ops cleanup, prevents wasted polling/cycles |
| Insufficient source data (empty title **and** empty content) | `services/cleaning.py` or Research's entry check | Flag/log, not necessarily a hard reject — short legitimate headlines exist |

---

## Milestones

### M1 — Source title normalization + early hard-rejection gates

- **Scope**: fix `RSSSourceAdapter`/`cleaning.py` per discovery §2's normalization contract; close
  the duplicate-`NEWS_ANALYSIS`-task active-only-dedup gap (discovery §8); exclude synthetic/test
  sources from the eligibility query.
- **Files likely changed**: `integrations/sources/rss_source.py`, `services/cleaning.py`,
  `integrations/sources/feed_parsing.py` (shared helper, if reused by Arxiv adapter too),
  `services/triage_orchestrator.py` or `workflow_service.create_task()`'s `_find_active_task()`
  (dedup scope fix), source eligibility query (collector or config).
- **Migrations**: No.
- **New config**: No (or an optional HTML-ratio threshold constant, not a new `Settings` field).
- **New provider calls**: Zero (fully deterministic).
- **Tests**: unit tests for the `html.unescape` + tag-strip + validate helper; RSS/Atom adapter
  tests using Google-News-shaped and llama.cpp-release-shaped HTML fixtures (empty, bare-HTML,
  bare-URL, overlong); regression test that duplicate-task creation is blocked across task
  history, not just active tasks; existing `tests/test_rss_source.py` stays green.
- **Acceptance criteria**: fixture-based replay of previously-malformed sources yields clean titles
  or a clean drop (never HTML in `NewsEvent.title`); no new duplicate `NEWS_ANALYSIS` task is
  created for an event that already has one, regardless of the existing task's status.
- **Rollback risk**: Low — isolated to the adapter/cleaning/dedup layer, no schema change.

### M2 — Category reliability

- **Scope**: replace hardcoded `EventCategory.UNKNOWN` at collection time with a deterministic
  mapping from each source's existing config-level tag/category (discovery §3, option 1). Do not
  introduce a new taxonomy. LLM-predicted category (option 2) is an explicit stretch goal, only
  worth doing if the deterministic mapping proves too coarse after this ships, and better bundled
  with M4 since it would touch the same write-back plumbing Scoring V2 needs.
- **Files likely changed**: `services/collector.py` (category assignment), source config loading
  path (verify whether `config/newsroom_sources_v1/sources/*.yaml` tags reach `NewsSource` rows or
  only live in-config — **must be confirmed first**, per discovery §9 risk).
- **Migrations**: Likely No, but **verify** whether source tags are already persisted to
  `NewsSource` before assuming so — if not, a small additive column may be needed. Flagged as an
  open unknown, not assumed either way.
- **New config**: No.
- **New provider calls**: Zero.
- **Tests**: mapping-table unit tests; collector test asserting category is assigned from a tagged
  source; regression test that untagged sources still correctly fall back to `UNKNOWN` (no silent
  misclassification).
- **Acceptance criteria**: newly collected events from tagged sources get a specific category other
  than `UNKNOWN`; delivered Telegram cards stop showing literal "UNKNOWN" for the majority of
  sources; untagged sources remain `UNKNOWN` by design.
- **Rollback risk**: Low.

### M3 — Engagement signal preservation

- **Scope**: capture real Telegram signals (views, forwards at minimum; reactions/replies as a
  stretch) at ingestion time in `TelegramSourceAdapter`, and channel reach/subscriber count via one
  additional Telethon call, cached/refreshed periodically. Persist both. This is the milestone most
  likely to need genuinely new plumbing, per discovery §5.
- **Files likely changed**: `integrations/sources/telegram_source.py` (capture fields),
  `database/models/news_event.py` and/or `database/models/news_source.py` (new nullable columns),
  a new `database/migrations/versions/*.py`, `capabilities/engagement_capability.py` (optionally
  add real signals as additional prompt context, without replacing the predicted score).
- **Migrations**: **Yes** — new nullable columns for raw views/forwards on `NewsEvent`-adjacent
  data and/or subscriber count on the source side. Keep additive-only/nullable for trivial rollback.
- **New config**: Possibly (toggle for real-engagement capture; refresh interval for subscriber
  counts).
- **New provider calls**: Zero **LLM** calls (Telethon/Telegram API calls are not LLM Gateway calls
  — call this out explicitly to avoid conflating the two cost categories).
- **Tests**: adapter unit tests with mocked Telethon `Message` objects exposing `.views`/
  `.forwards`; migration up/down test; persistence round-trip test.
- **Acceptance criteria**: new Telegram-sourced `NewsEvent` rows have raw views/forwards populated
  where the source API provides them; non-Telegram sources unaffected; existing tests green.
- **Rollback risk**: Medium — schema migration, but additive/nullable keeps it low-risk to revert.

### M4 — Editorial Scoring V2

- **Scope**: implement the design above — wire `EngagementCapability`'s existing output into
  `ScoringCapability`'s prompt context (currently missing, discovery §4b); restructure
  `prompts/scoring/*.yaml` to output structured relevance/importance/novelty sub-fields instead of
  one holistic score; compute the final weighted 0-100 score deterministically in Python from LLM
  sub-scores + freshness + source authority + engagement; make weights configurable; persist the
  final score somewhere visible across workflows (today it's invisible to CONTENT_GENERATION and
  never rendered in the Telegram card — discovery §4b) and optionally surface it in
  `bot/formatting.py`.
- **Files likely changed**: `capabilities/scoring_capability.py`, `prompts/scoring/` (new version),
  `core/config.py` (weight settings), `workflows/definitions/news_analysis.py` (ensure engagement's
  `step_results` are threaded into scoring's context if not already), `database/models/news_event.py`
  (add a `score` column — recommended, see below), `bot/formatting.py` (optional score display).
- **Migrations**: **Yes, recommended** — adding `NewsEvent.score` closes the discovery-confirmed gap
  where the score is computed then invisible outside `EditorialTask.workflow` JSON. Can be scoped
  out if the team prefers to keep this migration-free, but the gap is real and small to fix.
- **New config**: Yes (scoring weights as `Settings` fields).
- **New provider calls**: Zero net new — restructures and wires together two calls (`scoring`,
  `engagement_analysis`) that already run every NEWS_ANALYSIS cycle.
- **Tests**: pure-Python weighted-formula unit tests (no LLM involved); prompt schema-validation
  tests (must satisfy `tests/test_openai_strict_schema_compliance.py`'s strict-mode constraints);
  regression test that final score stays within 0-100; test that engagement demonstrably shifts the
  score in a constructed fixture.
- **Acceptance criteria**: score is produced by the documented, weighted, inspectable formula;
  engagement signal demonstrably influences it in tests; NEWS_ANALYSIS nominal call count stays at
  4 (no regression per discovery §7); score is queryable/visible outside `EditorialTask.workflow`.
- **Rollback risk**: Medium — prompt/schema changes can shift score distribution, and the existing
  `CONTENT_GENERATION_MIN_SCORE` threshold is tuned against the old distribution. Run M7 before
  fully relying on the new distribution against that threshold.

### M5 — Fact safety

- **Scope**: add the deterministic entity/claim-overlap check identified in discovery §6, inside
  `QualityCapability.execute()`, alongside its existing `_floor_validate()` check. Flag draft-body
  claims (numbers, named entities, capitalized multi-word phrases) absent from
  `title + content + summary + Research's facts`. On an unsupported claim: flag it on the output (at
  minimum) and, only when a claim is actually flagged, optionally re-invoke the existing
  `CopywritingCapability` for a rewrite pass (conditional reuse of an existing capability, not a new
  one).
- **Files likely changed**: `capabilities/quality_capability.py`, `prompts/quality/` (new version,
  add an `unsupported_claims`-style output field), `schemas/` (Quality's output schema and/or
  `ContentDraft`), possibly `database/models/content_draft.py` (a flag column, if editors should see
  this in the inbox).
- **Migrations**: Possibly — only if the fact-safety flag needs to be visible on `ContentDraft`
  itself rather than staying inside `EditorialTask.workflow` JSON like other step outputs today.
  Start without a migration (flag lives in workflow JSON) unless editor-visibility is required.
- **New config**: Maybe (toggle: auto-rewrite-on-flag vs. flag-only).
- **New provider calls**: Zero baseline (the overlap check is deterministic); conditionally +1 only
  for drafts that actually have a flagged claim (existing Copywriting capability re-invoked, not a
  new capability) — should be rare in practice.
- **Tests**: unit tests for the entity-overlap function using fixtures that reproduce the Phase 14.5
  finding (Andreessen Horowitz / Uber investor claims not in source) as a named regression case;
  Quality capability tests with and without flagged claims; spot-check false-positive rate against a
  sample of known-good drafts.
- **Acceptance criteria**: the specific Phase 14.5 example is caught by the new check in a
  regression test; no unconditional new LLM call is added; false-positive rate stays low on a
  known-good sample.
- **Rollback risk**: Low-medium.

### M6 — Tests and regression validation

- **Scope**: consolidate and run the full existing suite (`tests/test_capability_registry.py`,
  `tests/test_workflow_runner.py`, the Phase 9/10/13 regression suites,
  `tests/test_openai_strict_schema_compliance.py`) against all M1-M5 changes; add/expand contract
  tests for the new scoring formula and fact-safety gate; fix any regressions surfaced.
- **Files likely changed**: `tests/*` primarily; production code only if a regression fix is needed.
- **Migrations**: No (unless a regression fix requires one).
- **New config / new provider calls**: No.
- **Tests**: this milestone *is* the test work.
- **Acceptance criteria**: full suite green; all modified prompt schemas pass strict-mode
  compliance; no regression in existing Phase 9/10/13 contract tests.
- **Rollback risk**: N/A — validation only.

### M7 — Controlled live comparison

- **Scope**: confirm (read-only) that the background pipeline is healthy again — discovery §8 found
  it in a "BROKEN" (silently stalled) state as of the last health check, which must be independently
  reconfirmed or resolved (with the user's authorization) before this milestone can produce
  meaningful data. Then run a before/after comparison over a defined window: malformed-title
  incidence at delivery, category-UNKNOWN incidence, score distribution shift, engagement-wiring
  effect, and at least one attempted fact-safety-gate trigger, using the same read-only diagnostic
  methodology Phase 14.5 already established.
- **Files likely changed**: none required (or a scoped read-only diagnostic script mirroring Phase
  14.5's approach, plus a `docs/` report).
- **Migrations / new config / new provider calls**: No.
- **Tests**: N/A — live validation, not unit tests.
- **Acceptance criteria**: zero malformed titles reach delivery over the window; zero (or
  measurably fewer) cards show literal "UNKNOWN"; score distribution and engagement wiring visibly
  differ from the Phase 14.5 baseline; fact-safety gate demonstrably catches at least one real
  unsupported-claim case, or a documented zero-incidence result; no increase in nominal
  provider-call count per story beyond what M3-M5 explicitly justify.
- **Rollback risk**: None (observation only) — but the pre-existing worker-stall issue is a blocking
  dependency that must be raised with the user before this milestone starts.

---

## Cost/call-count summary across all milestones

| Milestone | Adds LLM calls? |
|---|---|
| M1 | Zero (deterministic) |
| M2 | Zero (deterministic default option) |
| M3 | Zero LLM calls (Telegram/Telethon API calls only, not LLM Gateway) |
| M4 | Zero net new (restructures + wires two already-running calls) |
| M5 | Zero baseline; conditional reuse of an existing capability only for flagged drafts |

No milestone unconditionally increases the 8-nominal/9-max LLM-call budget established in the
discovery report.

---

PHASE 15 M0 IMPLEMENTATION PLAN COMPLETE
