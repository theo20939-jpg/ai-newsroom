# Phase 16 — Image Intelligence — M0 Implementation Plan

Status: **M1 and M2 IMPLEMENTED** (docs/phase16_m1_native_media_ingestion_report.md, docs/
phase16_m2_secure_fetch_and_validation_report.md). M3–M8 remain plan only. See
`docs/phase16_image_intelligence_discovery_report.md` for the evidence this plan is built on.

## M2 architecture corrections (discovered during implementation)

- **The fetch module lives at `integrations/http/safe_fetch.py`, not `services/media_fetch.py`**
  as this plan originally guessed. It drives `httpcore.AsyncConnectionPool` directly rather than
  `httpx.Client`/`httpx.AsyncHTTPTransport`, because `httpx.AsyncHTTPTransport`'s public
  constructor does not expose the `network_backend` parameter IP-pinning requires - discovered by
  reading `httpx`'s actual installed source (0.28.1), not assumed. `httpcore.AsyncConnectionPool`
  itself does expose this (a documented, public extension point), which is what makes the whole
  mechanism possible without private-API reliance.
- **No separate MIME-sniffing library was added.** A minimal, self-written magic-byte sniffer
  (`services/image_validation.py::_sniff_signature`) covers every format M2 needs (JPEG/PNG/GIF/
  WebP/SVG/HTML-disguised-as-image) without a new dependency - `Pillow` (already planned) provides
  the second, decode-confirmed layer.
- **Concurrency limiting is in-process only** (global + per-host `asyncio.Semaphore`s, constructed
  fresh per `run_shadow_discovery()` call) - this plan's own "unless the current deployment has
  multiple concurrent content workers" condition for a distributed limiter was checked and does
  not currently hold (exactly one `content_worker` exists, and it processes events sequentially,
  per `tests/test_content_worker_cycle.py`'s own test naming), so no Redis-backed limiter was
  built. Documented as a limitation, not an oversight.
- **A real orchestration bug was found and fixed during implementation**: `safe_fetch()` correctly
  reports non-2xx HTTP statuses rather than raising, but the initial orchestration code didn't
  check `status_code` before treating a response body as valid content - fixed by adding an
  explicit check in both the article-metadata and image-fetch paths before any parsing/decoding.
  Caught by the M2 test suite itself failing, then passing after the fix - see the M2 report §19.

## M1 architecture corrections (discovered during implementation)

- **`RawNewsItem` gained one additive field (`native_media_hints`), contradicting this plan's
  original "no change to `RawNewsItem`... until M5's migration" statement below.** This is not a
  migration: `RawNewsItem` is a plain Pydantic schema, never a DB model — extending it costs
  nothing in schema-change terms, and every adapter that never sets the field (GitHub/HN/arXiv)
  is byte-for-byte unchanged. `NewsEvent`/`ContentDraft` (the actual DB models the original
  statement was really protecting) remain untouched, and no migration was added. The original
  wording was imprecise; the intent (no migration) held.
- **No per-`NewsEvent` metadata field exists reachable both at collection time and at
  `CONTENT_GENERATION` time** (confirmed by reading every `database/models/*.py` file — zero JSON
  columns on `NewsEvent`/`NewsSource`). M1 resolved this by splitting into two independent
  deliverables (Collector-time structured-log audit trail vs. CONTENT_GENERATION-time
  reconstruction from already-persisted `NewsEvent.content`/`url`) rather than adding a migration
  - see the M1 report §3 for the full reasoning. This is a real scoping constraint the original
  M0 plan's "Structured candidate contract... as an in-memory/`step_results` dict shape" language
  under-specified; M1's report is now the authoritative description of how that dict shape is
  actually populated.
- **GitHub release-body markdown-image extraction, listed as an M1 "minor addition" below, was
  deliberately NOT implemented** — out of scope for the milestone's actual delivery; GitHub/HN/
  arXiv all correctly produce empty native candidate lists in M1.
- **Open Graph/JSON-LD extraction was not built at all in M1**, not even as a disabled parser —
  the M1 task brief explicitly deferred it, superseding this plan's "M1 may build the parser but
  must not enable live fetching" language.

Architectural constraints preserved throughout: existing Workflow Engine (`workflows/runner.py`,
`workflows/registry.py`, `schemas/workflow.py` — unchanged), existing Capability Framework
boundaries (`capabilities/registry.py` unchanged — Image Intelligence is a deterministic service,
not a new registered Capability, per discovery §20), `NewsEvent`/`EditorialTask`/`ContentDraft`
model boundaries, existing worker separation (`content_worker` owns this), Telegram
editorial-only delivery. No auto-publication, no public-channel publishing, no LLM/vision calls
until M8, no approval-workflow redesign, no unrelated refactors.

---

## 1. Phase objective

Build the minimum architecture-preserving foundation so that a drafted `NewsEvent` can surface up
to five relevant, deterministically validated image candidates in the private Telegram Editorial
Inbox — without ever blocking text-only delivery, without any paid API call, and without a
database migration until the design is validated in shadow mode.

## 2. Architectural boundaries

- **New service, not a new Capability:** `services/image_intelligence.py`, invoked from
  `capabilities/executor.py` via `if step.capability == "copywriting":`, mirroring
  `apply_editorial_scoring_v2`/`apply_fact_safety`'s existing hook pattern exactly
  (`capabilities/executor.py:190-207`).
- **New shared fetch module:** one SSRF-safe HTTP fetch boundary (`services/media_fetch.py` or
  `integrations/media/fetcher.py` — named at M2 kickoff), used by every image-fetching code path.
  No adapter or service builds its own bare `httpx.AsyncClient` for image bytes.
- **No new worker.** `content_worker` (`worker/content_cycle.py`) owns the MVP end to end.
- **No change to `RawNewsItem`, `NewsEvent`, or `ContentDraft` schemas** until M5's migration.
- **No inline-keyboard code lands before M6** — `bot/keyboards/` stays an empty reserved package
  until then.

## 3. Milestones (M1–M8)

### M1 — Candidate ingestion — **IMPLEMENTED** (docs/phase16_m1_native_media_ingestion_report.md)

- **Scope actually delivered:** Telegram photo/document native metadata (Telethon, verified
  against real type shapes), RSS `media_content`/`media_thumbnail`/enclosure/inline-`<img>`
  (verified against real `feedparser` output), GitHub/HN/arXiv confirmed empty-and-correct. Open
  Graph/JSON-LD extraction was **not** built at all in M1 (fully deferred to M2, not even a
  disabled parser — see the architecture-corrections note above). GitHub release markdown-image
  extraction was scoped out. Candidate contract lives in `schemas/image_candidate.py`
  (`NativeMediaHint`/`ImageCandidate`/`ImageIntelligenceResult`) - two independent, non-migrated
  transport surfaces (Collector-time structured log; CONTENT_GENERATION-time reconstruction from
  persisted `NewsEvent.content`/`url`), not one unified in-memory/step_results pipeline as
  originally imagined - see the M1 report §3 for why.
- **Files actually changed:** `schemas/image_candidate.py` (new), `services/image_intelligence.py`
  (new), `schemas/raw_news_item.py` (additive field), `services/cleaning.py`, `integrations/
  sources/telegram_source.py`, `integrations/sources/rss_source.py`, `services/collector.py`,
  `core/config.py`, `capabilities/executor.py`. No `services/og_metadata.py` was created.
- **Tests actually delivered:** 47 tests in `tests/test_image_intelligence.py` plus adapter-level
  wiring tests in all five source-adapter test files, Collector-level tests, and CapabilityExecutor
  workflow-hook tests (real Postgres) — see the M1 report §16/§19 for exact totals.
- **Migration impact:** none, as planned.
- **Deployment impact:** none — `image_intelligence_mode` defaults to `"off"` (not `"shadow"` -
  see the architecture-corrections note above for why M1 chose a stricter default than this plan
  originally implied); shipped dormant, per plan.
- **Rollback:** as planned — config flip only, no code surgery.
- **Definition of Done:** met — see the M1 report's 400-event real-data backtest (§17) for
  evidence-matching candidate lists per source type, zero live network calls.
- **Non-goals:** held exactly as planned.

### M2 — Secure fetch and technical validation — **IMPLEMENTED** (docs/phase16_m2_secure_fetch_and_validation_report.md)

- **Scope actually delivered:** exactly as planned, with two refinements discovered during
  implementation. (1) No separate MIME-sniffing library was added - a minimal, self-written
  magic-byte sniffer in `services/image_validation.py` covers JPEG/PNG/GIF/WebP/SVG/HTML detection
  without a new dependency (only `Pillow` was added, as planned). (2) The fetch module lives at
  `integrations/http/safe_fetch.py`, not `services/media_fetch.py` as originally guessed - it
  drives `httpcore.AsyncConnectionPool` directly (a public API) rather than `httpx.Client`, because
  `httpx.AsyncHTTPTransport` does not expose the `network_backend` extension point IP-pinning
  requires (discovered by reading `httpx`'s actual source, not assumed - see the M2 report §3).
  Concurrency is in-process only (global + per-host `asyncio.Semaphore`s, not a distributed
  rate-limiter) - correct for the current single-`content_worker` deployment, documented as a
  limitation, not built further per the M0 plan's own "unless necessary" instruction.
- **Files actually changed:** `integrations/http/safe_fetch.py` (new), `services/
  article_metadata.py` (new - OG/Twitter/JSON-LD extraction), `services/image_validation.py` (new -
  Pillow decode/validation), `schemas/image_candidate.py` (additive `TechnicalValidation` + new
  enum values), `core/config.py` (M2 limit settings), `services/image_intelligence.py` (M2
  orchestration), `capabilities/executor.py` (one-line change: calls the new orchestration
  function), `pyproject.toml` (`Pillow>=11.0`).
- **Tests actually delivered:** 117 new tests (55 safe-fetch + 23 article-metadata + 25
  image-validation + 14 workflow-integration), all against a local `ThreadingHTTPServer` (used
  instead of `httpx.MockTransport` since M2 bypasses `httpx.Client` entirely - see the files-
  changed note above) plus direct DNS-resolver mocking for the SSRF matrix. Zero uncontrolled
  external network calls in the suite. Full repository suite: 1362 passed (up from M1's 1247 by
  exactly the 117 new tests, plus 15 pre-existing environment failures already proven at `133a22c`
  during M1, unrelated to M2).
- **Migration impact:** none, as planned.
- **Deployment impact:** **reproducible deployment succeeded** - `docker compose build` completed
  cleanly this time (M1's registry/package-index restriction did not recur), both
  `content_worker`/`automation_worker` images rebuilt with the new `Pillow` dependency and
  recreated; still gated `off` by default, verified inert in the freshly deployed container.
- **Rollback:** as planned - the fetch module is inert unless called; the mode flag stays `off`.
- **Definition of Done:** met - every SSRF/redirect/byte-limit/decode threat-model row has a
  passing, deterministic local-server test; a genuine end-to-end OG-image fetch, both against a
  local server and (in a separately bounded, 20-article live validation) against real public
  websites, succeeded.
- **Non-goals:** held exactly as planned - no quality/logo/duplicate filtering (M3), no ranking
  (M4); M2 does add exact-duplicate-URL consolidation (an M1-scope mechanism, unchanged, not new
  M2 dedup logic).

### M3 — Quality gate and deduplication

- **Scope:** hard-rejection gates and soft signals from discovery §12–13 (icons/logos/placeholders/
  ads, dimension/aspect-ratio gates); layered dedup from discovery §14 (canonicalized URL → Telethon
  media identifier → exact content hash → perceptual hash → crop heuristics), scoped within-event.
  Adds `imagehash` to `pyproject.toml`.
- **Files likely affected:** `services/image_intelligence.py` (extends M1's candidate list with
  `status`/`rejection_reasons`/hashes), `pyproject.toml` (`imagehash`).
- **Tests:** the quality matrix (small icon, tracking pixel, banner, valid landscape/portrait,
  corrupted image, placeholder) and the dedup matrix (identical URL, normalized CDN URL, exact
  hash, resized copy, recompressed copy, near-duplicate crop, distinct images) from discovery §12.
- **Migration impact:** none.
- **Deployment impact:** none — still `off` by default; first milestone whose output is worth
  reviewing in `shadow` mode on a sample of real events (manual/scripted review, not automated
  Telegram delivery).
- **Rollback:** same as M1/M2.
- **Definition of Done:** on a sample of real drafted events, hard-rejected candidates are
  manually spot-checked as correct rejections; no false-positive exact-duplicate merges of
  editorially distinct images.
- **Non-goals:** no relevance ranking yet (M4); no manual-review UI (that's M6's job, if ever).

### M4 — Deterministic relevance ranking

- **Scope:** the 0–100 bounded ranking formula from discovery §15 — provenance, technical quality,
  textual relevance (token overlap against the drafted `ContentDraft.title`/`body`), duplicate
  penalty, logo/banner penalty, discovery-method reliability, freshness. Configurable weights in
  `core/config.py`, summing to 1.0, following the `editorial_scoring_weight_*` precedent exactly
  (tested against defaults, not cross-field-validated, matching this Settings class's own
  established convention).
- **Files likely affected:** `services/image_intelligence.py`, `core/config.py` (new
  `image_intelligence_weight_*` settings).
- **Tests:** ranking matrix from discovery §15 — original-source-media priority, resolution
  ordering, logo penalty, missing-data neutral-not-bonus behavior, deterministic tie-breaking,
  source-type neutrality (no source type wins merely for having less metadata to evaluate).
- **Migration impact:** none.
- **Deployment impact:** none — output written into `EditorialTask.workflow.step_results` for the
  `copywriting` step, per discovery §11/§20; still no Telegram-visible change.
- **Rollback:** same as M1–M3.
- **Definition of Done:** for a sample of real drafted events with ≥2 discovered candidates, the
  top-ranked candidate is manually judged reasonable by an editor; component score breakdown is
  inspectable in `step_results` JSON.
- **Non-goals:** no image-content/semantic relevance claim beyond available metadata (explicit
  discovery §15 rule) — this is not vision-based ranking.

### M5 — Persistence and retention

- **Scope:** the first schema change in this phase. New `ImageCandidate` table (discovery §11's
  field set) via a real Alembic migration; move from `step_results`-scoped storage to stable
  per-`NewsEvent` identity; a retention/cleanup job (mirrors the "no existing cleanup worker"
  gap identified in discovery §9 — this is genuinely new infrastructure, not an extension); store
  bytes only for the ≤5 editor-facing finalists (discovery §9's storage-strategy recommendation).
- **Files likely affected:** `database/models/image_candidate.py` (new), one new
  `database/migrations/versions/*.py`, `services/image_intelligence.py` (write path changes from
  `step_results` to the new table), new retention job under `worker/` or a `scripts/` cron-style
  entry point matching this repo's existing script conventions.
- **Tests:** migration applies/rolls back cleanly against a disposable test DB; retention job
  correctly ages out stored bytes past a configurable window without deleting rows still linked to
  an undelivered/recent `ContentDraft`.
- **Migration impact:** yes — this is the one milestone where it's expected and justified (§21 of
  the discovery report explains why it was deferred this long).
- **Deployment impact:** requires the migration to run before this milestone's code deploys — first
  milestone with real deployment-order sensitivity in this phase.
- **Rollback:** the migration adds a new table only (no column changes to existing tables) — safe
  to leave un-rolled-back even if the milestone's code is reverted; the table simply goes unused.
- **Definition of Done:** candidates for a real event persist across separate `CONTENT_GENERATION`
  runs (the exact limitation discovery §22 flags about `step_results` no longer applies);
  retention job runs cleanly in a scheduled dry-run.
- **Non-goals:** no cross-event/global dedup queries yet (possible now, but not required this
  milestone) — keep scope to "persistence exists and is correct," not "every consumer of it is
  built."

### M6 — Telegram Editorial Preview

- **Scope:** the UX from discovery §17 — existing text card unchanged; new follow-up `send_photo`
  message with an inline keyboard (Prev/Next/Reject/Use-no-image/Open-source) for the top-ranked
  candidate when ≥1 exists. First inline-keyboard/callback-query code in this repository.
- **Files likely affected:** `bot/keyboards/` (first real content — currently an empty reserved
  package), new `bot/handlers/image_selection.py` (callback-query router), `services/
  telegram_notifier.py` (send the follow-up message after the existing card, never replacing it),
  `schemas/editorial_inbox.py` (if a new transport-neutral shape is needed for the image message —
  evaluate reuse of `EditorialInboxCard` first before adding a new schema).
- **Tests:** preview send, candidate selection, no-image path, source-link display, invalid
  callback handling, repeated/duplicate callback idempotency, missing-candidate edge case, and an
  explicit assertion that no public-channel send path is exercised anywhere in this milestone's
  tests (mirrors this repo's existing `content_generation_dry_run` safety-by-default posture).
- **Migration impact:** none (uses M5's table, already migrated).
- **Deployment impact:** first milestone with a real user-visible change — must ship behind the
  mode flag, defaulting to the pre-M6 behavior (existing text-only card, no follow-up message)
  until explicitly flipped, exactly matching `content_generation_dry_run`'s own "safe default,
  deliberate flip" precedent.
- **Rollback:** flip the mode flag back; no code removal needed.
- **Definition of Done:** manual, explicit dry-run verification (rendered payload inspected, not
  sent) before any live flip — mirroring `services/telegram_notifier.py`'s own existing dry-run
  discipline exactly. Live flip itself requires the same explicit authorization this document's own
  constraints require for any Telegram send.
- **Non-goals:** no redesign of the existing `/news` text-card flow; no public-channel exposure of
  any kind.

### M7 — Shadow and live validation

- **Scope:** run M1–M6 end to end against real, naturally arriving events for a validation window;
  review source coverage (does the priority order from discovery §7 actually hold up live?), false
  -rejection rate (are the M3 threshold guesses too aggressive?), duplicate-detection accuracy,
  latency, storage growth, and — once M6 is live — real Telegram UX friction.
- **Files likely affected:** none necessarily — this is a validation milestone, output is a report
  (`docs/phase16_m7_live_validation_report.md`, following this repo's own `phaseN_mX_..._report.md`
  naming convention), plus threshold/weight tuning in `core/config.py` based on findings.
- **Tests:** none new required beyond what M1–M6 already built; this milestone's own "test" is the
  live validation report.
- **Migration impact:** none, unless findings justify a schema adjustment (documented separately,
  not assumed here).
- **Deployment impact:** none beyond what M6 already shipped.
- **Rollback:** unchanged from M6.
- **Definition of Done:** a live validation report exists with concrete before/after numbers for
  each of the review dimensions above, and an explicit go/no-go recommendation for wider rollout.
- **Non-goals:** no new features — this milestone measures, it does not build.

### M8 — Optional AI/vision reranking (explicitly deferred)

- **Scope:** an *optional* later layer that reranks M4's deterministic shortlist using a vision-
  capable LLM call, once OpenAI (or another provider) quota is restored.
- **Explicit deferral conditions** (all four must hold before M8 starts):
  1. API quota is restored (verified live, not assumed).
  2. The deterministic foundation (M1–M7) is validated with real evidence, not just shipped.
  3. Cost is measured from M1–M7's real operation, not estimated in advance.
  4. A strict, enforced per-cycle provider-call budget exists for this specific feature — following
     this repository's own `llm_budget_mode`/`RedisBudgetGuard` precedent, not a new ad hoc limit.
- **Files likely affected:** not scoped here — genuinely future work, deliberately undesigned
  beyond "it would plug into the CapabilityExecutor/LLM Gateway machinery the same way every other
  AI capability already does, unlike M1–M7's deterministic service."
- **Non-goals for this document:** no formula, no prompt, no schema — designing M8 now would
  violate the M0 brief's own instruction not to plan around API access this project doesn't
  currently have.

## 4. Exact expected files/modules (cumulative, across all milestones)

New: `services/image_intelligence.py`, `services/media_fetch.py` (or `integrations/media/
fetcher.py`), `services/og_metadata.py`, `database/models/image_candidate.py`, one new Alembic
migration, `bot/handlers/image_selection.py`, contents of `bot/keyboards/`.

Modified: `capabilities/executor.py` (new `if step.capability == "copywriting":` hook), `core/
config.py` (new settings, all following existing `Field(default=..., gt=0)`/`Literal[...]`
conventions), `pyproject.toml` (`Pillow`, `imagehash`, a MIME-sniffing library), `services/
telegram_notifier.py` (M6 only — additive follow-up message).

Explicitly NOT modified: `workflows/runner.py`, `workflows/registry.py`, `schemas/workflow.py`,
`capabilities/registry.py`, `bot/formatting.py`'s existing card-rendering logic, `RawNewsItem`.

## 5. Schemas and persistence

M1–M4: no schema change — candidate dicts live inside `EditorialTask.workflow.step_results` JSON,
validated by a new Pydantic model (e.g. `schemas/image_candidate.py`, mirroring
`schemas/workflow.py`'s own `WorkflowStepResult` pattern: `frozen=True, extra="forbid"`) even
though it's not yet a DB table. M5: the same field set becomes a real `image_candidates` table via
Alembic, FK to `news_events.id` and nullable FK to `content_drafts.id`.

## 6. Security controls (summary — full detail in discovery §10)

One shared, SSRF-safe fetch module is the single enforcement point for: scheme allowlist, DNS/IP
validation pre-connect with pinned-IP-after-validation, redirect revalidation, strict timeouts,
streaming byte caps, decoded-pixel caps, MIME sniffing, format allowlist (no SVG), safe generated
filenames (content-hash-derived only), bounded concurrency, per-domain rate limits, no
credential-bearing headers on external fetches. TLS verification is never disabled.

## 7. Test matrix

Full matrix per discovery-report task brief (source parsing, security, quality, deduplication,
ranking, workflow, Telegram) is distributed across M1 (parsing), M2 (security), M3 (quality/dedup),
M4 (ranking), M6 (Telegram), with workflow-level tests (no candidate / one candidate / fewer than
five / five candidates / processing failure / text draft still succeeds / duplicate task
prevention / shadow mode no delivery change) added at M3–M4 once there's real behavior to assert
against. All tests use fixtures, `httpx.MockTransport` (this repo's own established pattern, per
`tests/test_rss_source.py`), or a local test HTTP server — never an uncontrolled external network
call, matching every existing test in this repository.

## 8. Deployment order

M1 → M2 → M3 → M4 (all dormant behind the mode flag, safe to deploy in sequence with zero user-
visible change) → M5 (migration must run before its code deploys) → M6 (first user-visible change,
behind an explicit dry-run-then-flip gate) → M7 (no deployment, validation only) → M8 (blocked on
external conditions, not scheduled).

## 9. Shadow rollout

`IMAGE_INTELLIGENCE_MODE=off` (default, byte-identical to today) → `shadow` (M3–M5: discover,
validate, rank, and persist candidates; zero Telegram behavior change — directly analogous to
`fact_safety_mode=shadow`'s own "compute and record, never change delivery" contract) → `enforce`
(M6: show candidates in the private Editorial Inbox — see discovery §19 for why `enforce` is
recommended over the task brief's original `editorial` naming, to match this repo's existing
three-state convention).

## 10. Live acceptance criteria

Before any flip to the delivery-changing mode: `IMAGE_INTELLIGENCE_MODE=shadow` has run against a
meaningful sample of real, naturally arriving drafted events (not synthetic data); the M7 report
shows an acceptable false-rejection rate on manual spot review; no duplicate-merge of editorially
distinct images observed; latency added to the `CONTENT_GENERATION` workflow stays within its
existing `timeout_seconds=120` budget; storage growth is bounded and matches the ≤5-finalists-only
policy; and an explicit, deliberate human decision authorizes the flip — mirroring
`content_generation_dry_run`'s own "never a silent path to live" precedent exactly.

## 11. Rollback

Every milestone through M4 is rollback-by-default (the mode flag stays `off`, nothing changes).
M5's migration is additive-only (new table, no existing-table changes) — safe to leave in place
even if M5's code is reverted. M6 rolls back by flipping the mode flag; no code removal required at
any milestone, matching `editorial_scoring_version`'s and `fact_safety_mode`'s own established
"config flip, not code surgery" rollback precedent.

## 12. Deferred AI work

M8 only, gated on all four conditions in §3's M8 section. No vision/LLM call of any kind exists
anywhere in M1–M7. No prompt engineering, no LLM Gateway wiring, no Capability registration for
Image Intelligence is planned before M8, and M8 itself remains undesigned in this document
deliberately.

## 13. Full Phase 16 Definition of Done

- A drafted `NewsEvent` with genuinely available images surfaces up to five deterministically
  validated, ranked, deduplicated candidates — never fabricated when fewer valid images exist
  (verified by M3/M4's own quality-gate and ranking test matrices).
- Text-only `ContentDraft` delivery is provably never blocked by any Image Intelligence failure
  mode (M1–M7's failure-behavior tests, discovery §19).
- Zero SSRF/decompression-bomb/oversized-download vulnerability in the shared fetch module (M2's
  full security test matrix passing).
- Zero LLM/paid-API call anywhere in the shipped M1–M7 system.
- No public-channel exposure at any point; private editorial delivery only, gated behind an
  explicit, deliberately-flipped mode setting at every stage that changes user-visible behavior.
- A real Alembic migration exists only from M5 onward, and only after M1–M4 were validated without
  one.
- A live M7 validation report exists with concrete evidence, not projected estimates, backing the
  go/no-go decision for M6's live flip.
