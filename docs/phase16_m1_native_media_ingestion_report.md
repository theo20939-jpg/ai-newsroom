# Phase 16 M1 — Native Media Candidate Ingestion — Report

Status: IMPLEMENTED. Zero-download, zero-LLM native image candidate discovery, gated `off` by
default (`IMAGE_INTELLIGENCE_MODE=off|shadow`). See `docs/phase16_image_intelligence_discovery_
report.md` and `docs/phase16_image_intelligence_implementation_plan.md` for the M0 evidence and
milestone plan this implementation follows.

---

## 1. M1 objective

Build the foundation for native image candidate ingestion — Telegram photo/document metadata and
RSS `media_content`/`media_thumbnail`/enclosure/inline-`<img>` metadata — without downloading a
single image byte, without any LLM/provider call, and without a database migration. Make upstream
native media *observable and auditable* (structured logs at collection time) and produce a shadow
candidate result inside `EditorialTask.workflow.step_results` at `CONTENT_GENERATION` time.

## 2. Starting architecture

At commit `133a22c` (Phase 16 M0 complete), confirmed by direct inspection:

- `RawNewsItem`/`CleanedItem`/`NewsEvent`/`ContentDraft` had **zero** image/media fields.
- `NewsEvent` has no JSON/JSONB column of any kind (`Enum`/`Text`/`Integer`/`DateTime` only).
- The only JSON columns anywhere are `AIExecution.response`, `ContentDraft.hashtags`,
  `EditorialTask.workflow`, `TelegramChannel.settings` (unused, per-channel, unrelated), and
  `User.permissions` — none reachable both at collection time and at `CONTENT_GENERATION` time.
- Telegram collection uses **Telethon** (`integrations/sources/telegram_source.py`), not aiogram —
  confirmed again directly in M1 (matches M0 §4).
- `SourceType.NEWS_API` covers GitHub Releases, Hacker News, and arXiv adapters — none has a
  dedicated image field.
- `capabilities/executor.py` already has a proven, zero-registry-change seam for deterministic
  post-processing: `if step.capability == "scoring":`/`"quality":` (Editorial Scoring V2, Fact
  Safety). M1 reuses this exact pattern for `"copywriting"`.

## 3. Structured media transport path — the central architectural finding

**There is no existing per-`NewsEvent` field reachable both at collection time (adapter/Collector,
`automation_worker`) and at `CONTENT_GENERATION` time (`content_worker`) — two separate Docker
processes, confirmed via `docker ps`.** Adding one would require a migration, which M1 must not
add. This is not a workaround-able gap; it is a hard architectural fact, verified by reading every
`database/models/*.py` file and confirming zero JSON columns on `NewsEvent`/`NewsSource`.

M1's resolution — two independent, non-redundant deliverables, explicitly separated per the task
brief's own "separate: A. source metadata preservation; from B. CONTENT_GENERATION candidate
consolidation" instruction:

- **(A) Collector-time preservation** (`services/collector.py::_log_image_intelligence`, called
  after `NewsEvent` is flushed so a real `event.id` exists): consumes the *full* source-native
  hints an adapter produced at fetch time (Telegram photo/document, RSS `media_content`/
  `media_thumbnail`/enclosure/inline-image) and emits **one structured log line** — a real,
  auditable record of what was seen. **Not persisted to PostgreSQL** — there is nowhere to put it
  without a migration, and M1 must not add one.
- **(B) CONTENT_GENERATION-time reconstruction** (`capabilities/executor.py`'s `"copywriting"`
  hook, `services.image_intelligence.reconstruct_hints_from_content`): best-effort recovery using
  **only** `NewsEvent.content`/`NewsEvent.url` — the two fields that *are* durably persisted.
  This correctly recovers real RSS inline-`<img>` candidates (the HTML is already stored verbatim
  in `content` — confirmed live: 22.1% of RSS rows contain `<img`, M0 discovery §8) and correctly
  finds **nothing** for Telegram/GitHub/HN/arXiv events, since none of those ever put an `<img>`
  tag into `content` (0/640 Telegram rows, 2/1593 NEWS_API rows contain `<img`).

Both call sites share one function, `services.image_intelligence.consolidate_candidates()` — no
duplicated rejection/dedup/identity logic.

This is a deliberate, honest scoping, not a partial implementation of a single pipeline: (A) is a
real, tested capability that will matter increasingly as more events are collected under M1's
code (going forward, not retroactively); (B) is what actually reaches the shadow `step_results`
today. Both are documented as such — never conflated.

## 4. Candidate schema

`schemas/image_candidate.py` (new file). Frozen, `extra="forbid"` Pydantic models, matching this
repository's own established schema convention (`schemas/workflow.py`, `schemas/capability.py`).

- `ImageDiscoveryMethod` — `telegram_photo`, `telegram_document`, `telegram_thumbnail` (reserved,
  unused in M1 — see §6), `rss_media_content`, `rss_media_thumbnail`, `rss_enclosure`,
  `rss_inline_image`, `source_native_unknown` (reserved).
- `ImageCandidateStatus` — `discovered`, `rejected_metadata`, `unavailable` (reserved, unused in
  M1 — no M1 code path produces it; documented as forward-compatible for a future milestone where
  a hint's referent is confirmed to have existed but is no longer retrievable, e.g. after an M2
  fetch attempt).
- `TelegramReference` — `message_id`, `grouped_id`, `media_kind`, `media_id`, `file_name`.
  Deliberately **excludes** `access_hash`/`file_reference` (Telethon's session-bound fields) — see
  §6.
- `NativeMediaHint` — what an adapter produces the instant it sees native media, before any
  `NewsEvent` exists.
- `ImageCandidate` — one consolidated, identified candidate (`candidate_id`, `event_id`,
  `source_type`, `discovery_method`, `status`, technical/editorial metadata, `rejection_reasons`,
  `warnings`, `discovery_order`, `discovered_at`).
- `ImageIntelligenceResult` — the top-level shape attached at `structured_output["image_
  intelligence"]` and logged at Collector time (`version`, `mode`, `event_id`, discovered/
  accepted/rejected counts, `candidates`, `generated_at`, `errors`).

No field represents downloaded bytes, a decoded/validated MIME type, a content hash, or a
perceptual hash — all explicitly deferred to M2/M3 per the M0 plan.

## 5. Candidate identity

`services.image_intelligence._compute_candidate_id()`: `sha256(event_id + discovery_method +
identity_key)`, mirroring `services/collector.py::_compute_hash`'s own established sha256
precedent — never Python's randomized `hash()`. Identity key:

- **Telegram**: `(message_id, grouped_id, media_kind, media_id)` — stable Telethon coordinates,
  never `access_hash`.
- **RSS**: the exact validated URL, **deliberately not canonicalized/stripped of query
  parameters** (discovery report §14: "prefer false duplicates remaining separate over incorrectly
  merging distinct assets" — some CDN query parameters select the actual image).

Verified deterministic and idempotent by `tests/test_image_intelligence.py::test_same_message_
processed_twice_produces_the_same_candidate_id` and `test_candidate_ids_remain_stable_across_two_
consolidation_runs`.

## 6. Telegram extraction

`services.image_intelligence.extract_telegram_native_media()` (`integrations/sources/
telegram_source.py`'s `_to_raw_item()` calls it). Verified against real Telethon type shapes
(`telethon.tl.types.Photo`/`PhotoSize`/`Document`/`DocumentAttributeFilename`/
`DocumentAttributeImageSize`, introspected directly via `inspect.signature`, not guessed):

- `Message.photo` → largest available `PhotoSize`'s `w`/`h` (a `PhotoStrippedSize` — no real
  dimensions — is correctly skipped in favor of a real-dimensioned size).
- `Message.document` → only when `mime_type` starts with `image/` **and** no
  `DocumentAttributeSticker`/`DocumentAttributeVideo`/`DocumentAttributeAudio` attribute is
  present (checked by class name, so it works identically against real Telethon objects and test
  fakes) — per the task brief's explicit "stickers/video/audio must never become image
  candidates."
- `Message.grouped_id` (Telegram's media-group/album identifier) is preserved on
  `TelegramReference.grouped_id` — but see the limitation in §21: only the one message in an album
  that carries a caption survives `services/cleaning.py::clean_item()`'s pre-existing
  "drop if `text is None`" gate, so sibling album photos on caption-less messages remain invisible
  in M1, unchanged from before this milestone.
- Caption (`Message.text`) is preserved, bounded to 500 characters.
- `TelegramReference` never carries `access_hash` or `file_reference` — Telethon's session-bound
  fields. Only `Photo.id`/`Document.id` (stable, non-secret per-file identifiers) are kept. This
  means M1's stored coordinates alone are **not** sufficient to download the file later without
  re-fetching the message via Telethon (which re-derives a fresh `access_hash`) — a real
  limitation of Telegram's file-reference model, not an M1 implementation gap, and documented
  explicitly rather than worked around.
- Every extractor is individually wrapped in `try`/`except` — a malformed/unexpected attribute
  shape on one (e.g. `.photo`) can never prevent extraction of the other (e.g. `.document`), and
  can never crash the adapter's own text collection.
- Video thumbnails (`TELEGRAM_THUMBNAIL`) are reserved in the enum but **not implemented** —
  deferred per the M0 task brief's own instruction ("should remain deferred unless the M0
  implementation plan explicitly included them in M1" — it did not).

## 7. RSS extraction

`services.image_intelligence.extract_rss_native_media()` (`integrations/sources/rss_source.py`'s
`_to_raw_item()` calls it). Verified directly against real `feedparser` output (not assumed):
`media_content`, `media_thumbnail`, `enclosures`, and raw HTML in `summary` are all genuinely
exposed by the already-installed `feedparser>=6.0` dependency — zero new library required.

Priority order (matches the M0 discovery hypothesis, §5): `media_content` → image `enclosure` →
`media_thumbnail` → inline `<img>`, tracked via each candidate's `discovery_order`.

- **Feed-level logo is architecturally excluded**, not merely filtered: `extract_rss_native_media`
  takes only one entry (`tests/test_image_intelligence.py::test_feed_level_logo_is_
  architecturally_never_read` asserts its signature has no path to `feedparser.parse(...).feed`)
  — a channel-level logo can never be mistaken for an article image here.
- Inline `<img>` parsing uses Python's stdlib `html.parser.HTMLParser` — no new dependency,
  tolerant of malformed HTML (wrapped in `try`/`except`, degrades to zero hints rather than
  crashing).
- Lazy-load attributes (`data-src`, `data-original`, `data-lazy-src`) are preferred over `src`
  when present (common real-world convention: a placeholder in `src`, the real image behind a
  `data-*` attribute).
- `srcset` is parsed for the largest valid `Nw` width descriptor; a `srcset` with no parseable
  width descriptor is ignored (falls back to `src`/lazy-load attributes) with an explicit
  `malformed_srcset_ignored` warning — never guessed at via density (`x`) descriptors alone.
- Relative and scheme-relative URLs are resolved against the entry's own article URL via
  `urllib.parse.urljoin`.
- HTML entity decoding is automatic (`HTMLParser(convert_charrefs=True)`, the default).

## 8. GitHub/HN/arXiv behavior

Confirmed by direct adapter inspection (M0 §6) and re-verified in M1: none of the three
NEWS_API-category adapters has a dedicated image field. M1 deliberately does **not** implement
GitHub release-body markdown-image extraction (`![...]()`) — out of the M0 plan's explicit M1
scope. `RawNewsItem.native_media_hints` defaults to `[]`; none of `github_source.py`/
`hacker_news_source.py`/`arxiv_source.py` was modified. New tests
(`test_github_releases_produce_no_native_image_candidates`, `test_hacker_news_produces_no_native_
image_candidates`, `test_arxiv_produces_no_native_image_candidates`) confirm this is treated as
correct, non-error behavior, not a gap.

## 9. Metadata normalization

Extraction functions interpret HTML/feed structure (URL resolution, lazy-load/`srcset`
preference) — a "what does this markup mean" concern. **Validation is centralized** in
`consolidate_candidates()` (§10) — a "is this safe to keep" concern — deliberately kept separate
so extraction functions stay simple and every rejection rule lives in exactly one place.

## 10. Metadata rejection rules

`services.image_intelligence._validate_remote_url()`, applied centrally in
`consolidate_candidates()`: empty URL, missing scheme, unsupported scheme (`data:`, `javascript:`,
`file:`, anything other than `http`/`https`), and malformed URL (no `netloc`) are all rejected
with a specific `rejection_reasons` entry — never silently dropped, always auditable on the
resulting `ImageCandidate` (`status=rejected_metadata`). This is metadata-stage validation only —
no candidate is ever claimed safe to *download* (that determination belongs to M2's SSRF-safe
fetch boundary).

## 11. Duplicate consolidation

Within one event only (per M0 discovery §14's scoping): identical identity keys (§5) are merged,
keeping the higher-priority discovery method's candidate and marking the later duplicate
`rejected_metadata` with reason `duplicate_within_event` — auditable, not silently dropped.
Verified: `test_duplicate_url_from_multiple_rss_fields_consolidates_safely` (the higher-priority
`rss_media_content` wins over a same-URL `rss_enclosure`), `test_two_distinct_urls_remain_
separate`, `test_duplicate_execution_does_not_append_duplicate_candidates` (idempotent re-runs).
Cross-event and global dedup remain out of scope (deferred to M5's dedicated table, per the M0
plan).

## 12. Workflow integration

`capabilities/executor.py`: a new `if step.capability == "copywriting" and settings.image_
intelligence_mode == "shadow":` block, positioned immediately after the existing `"scoring"`/
`"quality"` hooks, calling `self._attach_image_intelligence()`. This:

- Never touches `structured_output`'s existing keys — only adds a new `"image_intelligence"` key
  (verified: `test_shadow_mode_does_not_change_drafted_text_fields`).
- Never runs for any other step — verified structurally
  (`test_image_intelligence_only_runs_for_the_copywriting_step`: a `"quality"` step in the same
  workflow run has no `"image_intelligence"` key in its own result).
- Is wrapped in its own `try`/`except Exception`, mirroring `apply_fact_safety`'s "must not affect
  delivery" discipline exactly — a failure inside reconstruction/consolidation is logged
  (`image_intelligence_workflow_attach_failed`) and swallowed, never fails the step
  (`test_image_intelligence_attach_failure_does_not_fail_the_step`).
- Requires one new DB read (`session.get(NewsSource, news_event.source_id)`) to resolve
  `source_type` — a local Postgres query, not a network fetch; consistent with this method's
  existing density (two `session.get()` calls already happen per step).

`services/collector.py::_process_item`: one line added after `report.events_created += 1`,
calling `_log_image_intelligence(event.id, source.type, cleaned.native_media_hints)` — after the
flush, so a real `event.id` exists; wrapped in its own `try`/`except`, never affects the
already-committed `NewsEvent`.

## 13. Configuration mode

`core/config.py`: `image_intelligence_mode: Literal["off", "shadow"] = "off"`. Two-state for M1
(`"editorial"`, the state that changes Telegram output, does not exist yet — reserved for M6).
Default `"off"` — unlike `fact_safety_mode`'s `"shadow"` default, M1 defaults to `"off"` since this
is a brand-new, zero-live-validation capability; M7's own live-validation milestone is the gate
for even a shadow-by-default posture. Not added to `.env`/`.env.example` — process-scoped test
overrides only (`monkeypatch.setattr(settings, "image_intelligence_mode", ...)`), per the task
brief's explicit instruction.

## 14. Failure isolation

Every layer fails closed toward "no image data," never toward "broken pipeline":

- Telegram: each of `_telegram_photo_hint`/`_telegram_document_hint` wrapped individually.
- RSS: each `media_content`/`enclosure`/`media_thumbnail` item and the inline-HTML parse wrapped
  individually; the adapter's own call site (`_safe_extract_native_media`) wraps the whole
  extraction call as a second layer.
- Collector: `_log_image_intelligence` wrapped, logs `image_intelligence_collector_logging_
  failed`, never raises past itself.
- `CapabilityExecutor`: `_attach_image_intelligence` wrapped, logs `image_intelligence_workflow_
  attach_failed`, returns `structured_output` completely unchanged on any failure.

No test failure, malformed source media, or reconstruction error was found (in either the test
suite or the 400-event live backtest, §17) that propagates past its containing layer.

## 15. Files changed

**New**: `schemas/image_candidate.py`, `services/image_intelligence.py`,
`scripts/phase16_m1_image_intelligence_backtest.py`, `tests/test_image_intelligence.py`,
`tests/test_collector_image_intelligence.py`, `tests/test_capability_executor_image_intelligence.py`.

**Modified**: `schemas/raw_news_item.py` (additive `native_media_hints` field), `services/
cleaning.py` (threads the field through `CleanedItem`), `integrations/sources/telegram_source.py`,
`integrations/sources/rss_source.py` (both call their respective extraction function),
`services/collector.py` (Collector-time logging hook), `core/config.py` (`image_intelligence_
mode` setting), `capabilities/executor.py` (CONTENT_GENERATION-time reconstruction hook), plus
one additive test each in `tests/test_telegram_source.py`, `tests/test_rss_source.py`,
`tests/test_github_source.py`, `tests/test_hacker_news_source.py`, `tests/test_arxiv_source.py`.

**Explicitly not modified**: `workflows/runner.py`, `workflows/registry.py`, `schemas/workflow.py`,
`capabilities/registry.py`, `bot/` (any file), `database/models/*.py`, any Alembic migration,
`.env`.

## 16. Tests

See §19 for exact totals. New/extended test files (all offline — fixtures, synthetic
Telethon-shaped dataclasses matching `tests/test_telegram_source.py`'s own established pattern,
plain dicts for feedparser-shaped entries, `httpx.MockTransport` for adapter-level HTTP, real
Postgres with per-test rollback for workflow-level tests — no test makes an uncontrolled external
network call):

- `tests/test_image_intelligence.py` — 47 tests: Telegram extraction, RSS extraction/URL
  handling, consolidation/dedup/rejection, serialization/identity stability.
- `tests/test_telegram_source.py`, `tests/test_rss_source.py` — adapter-level wiring (hints
  actually reach `RawNewsItem`, not just the extraction function in isolation).
- `tests/test_github_source.py`, `tests/test_hacker_news_source.py`, `tests/test_arxiv_source.py`
  — one additive test each confirming empty, non-error native candidate behavior.
- `tests/test_collector_image_intelligence.py` — mode off/shadow logging, non-blocking failure.
- `tests/test_capability_executor_image_intelligence.py` — mode off/shadow, unchanged
  copywriting fields, step-scoping, non-blocking failure, real Postgres.

## 17. Real-data backtest

`scripts/phase16_m1_image_intelligence_backtest.py`, read-only, run against the live database
(400 most recent events, 151 RSS / 241 NEWS_API / 8 Telegram):

| Source | Events | Candidates discovered | Candidates accepted | 0 candidates | 1 | 2-5 | >5 |
|---|---|---|---|---|---|---|---|
| RSS | 151 | 37 | 37 (100%) | 119 | 27 | 5 | 0 |
| NEWS_API | 241 | 0 | 0 | 241 | 0 | 0 | 0 |
| TELEGRAM | 8 | 0 | 0 | 8 | 0 | 0 | 0 |

0 malformed/error events out of 400. All 37 discovered candidates were `rss_inline_image` (the
only discovery method recoverable from already-persisted `NewsEvent.content` — §3). Payload size:
229–1,247 bytes (avg 280.5) — well within any reasonable bound. 24.5% of sampled RSS events
(37/151) have a recoverable inline image, consistent with the M0 discovery report's independent
22.1% full-table estimate (§8 there) — a real, if imperfect, cross-validation of both figures.

**This backtest exercises the reconstruction path (§3, deliverable B) only.** The richer
adapter-time extraction (Telegram photo/document, RSS `media_content`/`media_thumbnail`/
`enclosure`) cannot be backtested against historical data — the raw Telethon/feedparser objects it
needs were never persisted for events collected before this milestone. That capability is instead
validated by `tests/test_image_intelligence.py`'s synthetic-fixture unit tests (§16) and will only
produce real candidates for events collected *after* M1 deploys — this is stated as a limitation,
not glossed over (§21).

## 18. Deployment

`content_worker` (imports `capabilities/executor.py`) and `automation_worker` (imports
`services/collector.py`, `integrations/sources/*`) are the two services whose imports actually
change; `news_analysis_worker` does not import any changed module (`NEWS_ANALYSIS`'s workflow has
no `"copywriting"` step) and was left untouched.

**Environment limitation encountered and worked around:** `docker compose build automation_worker
content_worker` failed repeatedly — first at `FROM python:3.12-slim` (`failed to resolve source
metadata ... TLS handshake timeout` against `registry-1.docker.io`), then, on a later attempt that
got further, at the `pip install .` layer (also network-dependent) — both failures are the same
restricted/unreliable outbound network access this sandbox already exhibited during Phase 16 M0's
bounded article-page sample (discovery report §7). This is an environment constraint, not an M1
code issue: the currently-running images (`ai-newsroom-automation_worker:latest`,
`ai-newsroom-content_worker:latest`) were built before this restriction was hit and remain valid;
only *rebuilding* them requires registry/PyPI access this sandbox doesn't reliably have right now.

**Workaround used** (reversible, no `.env` change, no migration): the nine changed/new production
files were copied directly into both running containers' filesystem via `docker cp` (e.g. `docker
cp services/image_intelligence.py ai_newsroom_content_worker:/app/services/image_intelligence.py`),
then each container was restarted (`docker restart`) so its Python process picked up the new code.
This validates the exact code that will be committed, running under the real Python 3.12 runtime
with the real installed dependencies, without requiring a new image layer. **A proper `docker
compose build` should still be run once registry/PyPI access is available**, before this is
treated as a permanent production deployment — the `docker cp` patch does not survive a future
`docker compose up`/container recreation from the (still old) image.

## 19. Shadow validation

`IMAGE_INTELLIGENCE_MODE` defaults to `off` in code — nothing changes until an operator explicitly
sets it. Shadow-mode validation was run two ways, both process-scoped (no persistent `.env`
change, no manually-triggered workflow, no synthetic `NewsEvent`):

1. **The 400-event live backtest (§17)** — `mode="shadow"` passed directly to `consolidate_
   candidates()` as a function argument against real, already-persisted, naturally-collected
   events. Confirms real RSS events produce real candidates (37/151), real Telegram/NEWS_API
   events produce zero candidates without error (0/249), and the reconstruction path never raises.
2. **`tests/test_capability_executor_image_intelligence.py`** (real Postgres, `monkeypatch.
   setattr(settings, "image_intelligence_mode", "shadow")`) — proves the exact same code path
   `capabilities/executor.py` uses in production behaves correctly end-to-end through a real
   `WorkflowRunner` run, including the "does NOT change copywriting's own output" and "step-scoped,
   never touches other steps" guarantees.

3. **Post-deployment live observation** (§18's `docker cp` + restart): both containers restarted
   cleanly with zero import errors and zero exceptions traceable to any M1 code. `automation_
   worker` ran a real collection cycle against live Telegram channels (`@habr_com`, `@vcnews`,
   `@rozetked`, `@d_code` — Telethon connected and fetched 50 messages from each) and live RSS
   feeds (e.g. `knowyourmeme.com/newsfeed.rss` — 4 entries fetched) through the modified
   `telegram_source.py`/`rss_source.py`/`collector.py` with no crash. `content_worker` restarted,
   re-registered all six capabilities cleanly (proving `capabilities/executor.py` still imports
   and initializes correctly), and ran a real `CONTENT_GENERATION` task through to its normal,
   pre-existing failure mode (`copywriting` failing on the pre-existing `insufficient_quota`
   block, logged as `content_generation_task_failed`) — exactly the pre-M1 behavior, confirming
   the new `if step.capability == "copywriting" and image_intelligence_mode == "shadow":` branch
   is inert (mode is `"off"`) and does not interfere with the existing failure path. The worker's
   queue continued processing the next task normally afterward, with no crash or hang. Some
   individual source fetches failed with `ConnectTimeout`/`Temporary failure in name resolution`
   during this observation — the same sandbox network flakiness noted in §18, unrelated to M1 and
   already handled by `services/collector.py`'s pre-existing per-source retry/skip logic.

**A true end-to-end live run through the actual running `content_worker`** (real `CONTENT_
GENERATION` cycle reaching the "copywriting" step naturally) could not be exercised: this
project's OpenAI quota is `insufficient_quota`-blocked (confirmed independently in Phase 16 M0 and
still true here), so the real "copywriting" capability call fails *before* reaching the M1 hook at
all — a pre-existing condition completely unrelated to M1. This is exactly the scenario the M1
task brief's own Step 16 anticipates ("If OpenAI quota prevents CONTENT_GENERATION from reaching
the integration seam: validate adapter persistence and service consolidation separately. Do not
classify the lack of CONTENT_GENERATION as an M1 code failure.") — items 1 and 2 above are that
separate validation, deliberately substituting a fake `copywriting` capability so the workflow
mechanics are proven independent of the quota block.

## 20. Zero-cost confirmation

Zero OpenAI/LLM/vision/paid-API calls were made anywhere during M1's implementation, testing, or
validation. `services/image_intelligence.py` imports no HTTP client, no LLM Gateway, no provider
SDK — grep-verifiable (`import httpx`/`import openai`/`llm_gateway` all absent from the file).

## 21. Known limitations

- **`step_results` is task-scoped, not event-scoped** (M0 discovery §22, reconfirmed here): a
  retried `CONTENT_GENERATION` run does not automatically see a prior run's discovered candidates.
  Accepted, documented — resolved only once M5 adds the dedicated table.
- **Collector-time hints (deliverable A) never reach `step_results` (deliverable B)** — the two
  surfaces are independent by design (§3), not yet reconciled. M5's migration is the natural point
  to unify them.
- **Media-group siblings without their own caption are invisible** — `clean_item()`'s pre-existing
  "drop if `text is None`" gate (unchanged in M1) means only the one captioned message in a
  Telegram album ever becomes a `NewsEvent` at all, so only that message's photo is ever a
  candidate. Not fixed in M1 — a bigger, orthogonal behavior change, out of this milestone's scope.
- **Telegram file-reference/`access_hash` expiry**: `TelegramReference` stores only `Photo.id`/
  `Document.id`, not `access_hash` (session-bound, expires) — later milestones must re-fetch the
  message via Telethon to obtain a fresh `access_hash` before any download, not merely read the
  stored `media_id`.
- **GitHub release-body markdown images are not extracted** — deliberately out of M1 scope (§8).
- **The 400-event backtest (§17) validates reconstruction only**, not the richer adapter-time
  extraction — see §17's own caveat.

## 22. M2 starting point

`services/image_intelligence.reconstruct_hints_from_content`/`extract_*_native_media` produce
metadata-only `NativeMediaHint`s with `remote_url` values that have passed scheme/malformed-ness
validation but are **not yet safe to fetch** (§10). M2's job: the shared SSRF-safe fetch module
(discovery report §10 — DNS/IP validation with pinned-IP-after-validation, redirect revalidation,
byte/pixel caps, MIME sniffing, no SVG) that actually downloads bytes for candidates M1 already
identified, plus enabling the Open Graph metadata path M1 deliberately left disabled (extraction
parser may be built in M1's spirit, but live fetching stays gated until M2's safety boundary
exists, per the M1 task brief's explicit "Article-page Open Graph fetching is deferred").

## 23. Rollback instructions

`IMAGE_INTELLIGENCE_MODE` already defaults to `"off"` in code — no `.env` change is needed to roll
back a default deployment. If an operator had explicitly set it to `"shadow"`, reverting to `"off"`
(or unsetting the variable) restores byte-for-byte pre-M1 behavior; no code path needs to be
reverted, mirroring `fact_safety_mode`/`editorial_scoring_version`'s own established "config flip,
not code surgery" rollback precedent. No migration was added, so there is nothing to roll back at
the schema level.

## Validation totals (Step 13)

- **New/extended M1 tests**: 107 passed, 0 failed (`tests/test_image_intelligence.py` [47],
  `tests/test_collector_image_intelligence.py` [4], `tests/test_capability_executor_image_
  intelligence.py` [6], plus additive tests in `tests/test_telegram_source.py`, `tests/
  test_rss_source.py`, `tests/test_github_source.py`, `tests/test_hacker_news_source.py`,
  `tests/test_arxiv_source.py`).
- **Full repository suite**: 1247 passed, 15 failed (1262 collected). All 15 failures were
  reproduced identically against commit `133a22c` (pre-M1) using `git stash`/`git stash pop` —
  proven pre-existing, unrelated to M1:
  - 12 failures (`test_capability_executor.py` ×8, `test_editorial_scoring.py` ×2, `test_fact_
    safety.py` ×2): all assert `ai_executions` row count `== 0` within a rolled-back test
    transaction, but the live `ai_executions` table already has 82 real rows from the continuously
    -running `news_analysis_worker`/`content_worker` — a `SELECT COUNT(*)` sees all
    already-committed rows regardless of the test's own transaction boundary. Environment
    pollution from live processing, not a code defect.
  - 3 failures (`test_content_generation_integration.py` ×1, `test_content_worker_cycle.py` ×2):
    all assert `settings.content_generation_dry_run is True`, but this environment's `.env` sets
    `CONTENT_GENERATION_DRY_RUN=false` (confirmed by direct read) — live editorial delivery is
    intentionally enabled here, contradicting the test's assumption of the code default.
  - (A 16th failure, `test_triage_orchestrator_cycle.py`, appeared in one full-suite run and not
    the other, on both the pre-M1 and M1 code — a pre-existing flaky test driven by concurrent
    live-worker DB activity, not a deterministic M1 regression.)
- **Ruff**: `All checks passed!` (whole repository).
- **mypy** (all 9 changed/new production files): `Success: no issues found`. The 6 pre-existing
  `import-untyped` warnings for `feedparser`/`telethon` (no bundled type stubs) and one
  pre-existing `_to_raw_item` argument-type note in `integrations/sources/telegram_source.py` were
  reproduced identically at commit `133a22c` — zero new mypy findings from M1.
- **Secret scan**: clean — every `access_hash`/`SecretStr` match in the diff is either this
  repository's pre-existing `core/config.py` field declarations (unchanged placeholder values) or
  M1's own documentation/code explaining that `access_hash` is deliberately *never* stored.
- **`git diff --check`**: clean (exit 0). **`.env`**: not staged, not modified.
- **Real-data backtest**: 400/400 events processed with zero errors (§17).

## 24. M1 verdict

See the final response for the deployment record and the formal verdict line.
