# Phase 19 M0 — Repository and Real-Data Audit

Consolidates every fact gathered during Phase 19's three planning-review passes, verified by
direct code read, into one reference document — later milestones cite this instead of
re-deriving these facts. No code changes in this milestone.

## 1. The verified selection → content-generation call path

`worker/content_cycle.py::_select_eligible_events()` is the real editorial selection cutoff:
SQL-side finds `NewsEvent` rows with a `COMPLETED` `NEWS_ANALYSIS` task, fresh
(`content_generation_scan_limit`, default 50 candidates scanned), not already having a
`CONTENT_GENERATION` task; Python-side filters to `score >= settings.content_generation_min_score`
(default 70), capped at `content_generation_batch_size` (default 5).

`scripts/run_content_generation.py::run_content_generation_for_event()` is the **only** production
call site that creates a `CONTENT_GENERATION` `EditorialTask` (`workflow_service.create_task()`)
immediately before starting `WorkflowRunner.run()`. `worker/analysis_cycle.py` never creates
`CONTENT_GENERATION` tasks — it strictly advances `NEWS_ANALYSIS` tasks.

**Phase 19 M1's article-acquisition hook sits between task creation and `WorkflowRunner.run()`
inside `run_content_generation_for_event()`** — after selection, after task creation, before the
workflow (and Copywriting) starts. Collector, Analysis, Engagement, Scoring, and the existing
selection pipeline are untouched — confirmed by a regression run of
`tests/test_content_worker_cycle.py`/`test_content_worker_cycle_image_preview.py`/
`test_analysis_worker_cycle.py` showing only the pre-existing baseline failures (documented §6).

## 2. Safe-fetch and HTML-parsing precedents reused by M1/M2

- `integrations/http/safe_fetch.py::safe_fetch(url, *, policy)` — the sole SSRF-safe fetch
  boundary in this codebase. DNS resolved once, IP validated against a blocklist before
  connecting, TCP pinned to that IP, redirects followed explicitly and re-validated per hop.
  Already used by `services/image_intelligence.py::_fetch_article_metadata_hints()` for article
  HTML — M1 reuses this identical mechanism, from a new, selection-gated call site.
- `_validate_url()` (private to `safe_fetch.py`) — structural URL validation (scheme/credentials/
  hostname) reused directly by `services/article_acquisition.py::resolve_canonical_url()` to
  validate a discovered canonical URL before trusting it as a reuse key, without a second fetch.
- `services/article_metadata.py::_MetadataCollector(HTMLParser)` — stdlib-only HTML parsing,
  explicitly documented as avoiding a new dependency (no BeautifulSoup/lxml). M1's
  `_ArticleTextCollector` mirrors this exact technique for body-text + canonical-link extraction.

## 3. RSS enclosure / video-metadata parsing (relevant to a later milestone, M10)

`services/image_intelligence.py::_enclosure_hint()` already parses RSS enclosures and explicitly
discards non-image MIME types: `if not mime_type.startswith("image"): return None`. This is the
exact mirror point for a future video-accepting parallel function — video enclosures are already
visible to the parser today, just discarded.

## 4. Telegram length-budget and quote-rendering mechanics (relevant to a later milestone, M5)

`bot/formatting.py::_telegram_utf16_length()` is the sole authoritative length check
(`len(text.encode("utf-16-le")) // 2`); `SAFE_LIMIT = 4096`. The `<blockquote>` block is appended
with no length check of its own today — confirmed unbounded. Photo captions already use a
separate `CAPTION_SAFE_LIMIT = 1024` in three places; `bot/meme_preview_formatting.py` uses plain
`len()` instead of the UTF-16-aware measurement the other two use (a pre-existing inconsistency,
out of scope for the meme pipeline per M15).

## 5. Vision-input plumbing (relevant to a later milestone, M13)

`RoutingCriteria.requires_vision`, `GenerateRequest.modalities`, `ContentPart` (with
`artifact_ref`+`mime_type`), and `openai_adapter.py::_translate_content_part()`'s `input_image`
translation are all real, already-wired code. All three catalog models
(`gpt-5.6-sol/terra/luna`) already declare `supports_vision=True`. No capability constructs an
image-bearing request today.

## 6. Established pre-existing test baseline (unrelated to any Phase 19 change)

Confirmed via `git stash` comparison during M1/M2 implementation:
- `tests/test_capability_executor.py` (8 tests) and similar files assert
  `_ai_execution_count(db_session) == 0`, which collides with ~4863 real historical `AIExecution`
  rows already present in this dev database — a known, pre-existing, environment-specific issue
  (non-default dev DB state), not caused by any code change.
- `tests/test_phase10_workflow_integration.py::test_content_generation_reaches_completed_in_exact_step_order`
  fails identically on a clean pre-Phase-19 baseline (stray `image_intelligence` step-result key,
  from this dev `.env`'s non-default `image_editorial_preview_enabled=True`).
- `tests/test_content_worker_cycle.py`/`test_content_worker_cycle_image_preview.py` have 3
  pre-existing failures from the same non-default `.env` values
  (`content_generation_dry_run=False`, `image_editorial_preview_enabled=True`).

All three patterns were already documented extensively during Phase 18.10's own validation work
and are re-confirmed, not newly discovered, here.

## 7. The Telegram reply-threading shadow-mode gap (Correction 1, already-committed Phase 18.10 code)

`worker/content_cycle.py:219-245` (as committed in Phase 18.10, commit `634a8b9`) computes and
applies a Telegram `reply_to_message_id`, and can skip a send entirely (fail-closed `continue`),
the moment `story_memory_mode != "off"` — i.e. `"shadow"` was not actually safe for Telegram
delivery as shipped. Phase 19 M7 (a later milestone, not part of this M0-M2 checkpoint) introduces
an independent `telegram_story_reply_mode` setting to close this gap; it is recorded here because
it materially changes the risk characterization of `story_memory_mode` for anyone reviewing this
audit before M7 lands.
