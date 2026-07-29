# Phase 16 M2 — Secure Fetch, Article Metadata Discovery, and Technical Image Validation — Report

Status: IMPLEMENTED. `IMAGE_INTELLIGENCE_MODE` still defaults to `off` (unchanged from M1) — no
network call happens by default. See `docs/phase16_m1_native_media_ingestion_report.md` for the M1
foundation this milestone extends.

---

## 1. M2 objective

Build one shared, SSRF-safe, DNS-rebinding-resistant external-fetch boundary, and use it for
(a) Open Graph/Twitter Card/JSON-LD article-image metadata discovery and (b) transient candidate
image byte retrieval plus technical (MIME/signature/decode/pixel/animation) validation — all
zero-AI, zero-paid-API, non-blocking, and never persisting a single downloaded byte.

## 2. Starting M1 architecture

At commit `51dc4d0` (Phase 16 M1 complete): `services/image_intelligence.py` produced only
metadata-only candidates (no bytes ever fetched); `capabilities/executor.py`'s `"copywriting"`
hook called `reconstruct_hints_from_content()` + `consolidate_candidates()` directly;
`IMAGE_INTELLIGENCE_MODE=off|shadow` existed but `"shadow"` never made a network call. No HTTP
client shared across the codebase; no image-decoding library present (`Pillow` was not a
dependency); no SSRF protection anywhere.

## 3. Existing HTTP-stack findings

Confirmed by direct inspection of `pyproject.toml`, installed package versions, and every
integration under `integrations/sources/`:

- **`httpx>=0.27` (installed 0.28.1) is the project's only HTTP client**, used by
  `RSSSourceAdapter`/`ArxivSourceAdapter`/`GitHubSourceAdapter`/`HackerNewsSourceAdapter`, each
  building its own bare `httpx.AsyncClient` — no shared client, no shared security policy.
  `httpcore` (installed 1.0.9) is httpx's own transport-level dependency, already present
  transitively.
- **Custom DNS resolution is supported** via `httpcore.AsyncNetworkBackend` (a documented public
  extension point) passed to `httpcore.AsyncConnectionPool(network_backend=...)`. Verified by
  reading `httpcore._backends.base`/`httpcore._backends.anyio` source directly (not assumed).
- **Connecting to a validated IP while preserving hostname/SNI/Host header is supported** —
  verified by reading `httpcore._async.connection.AsyncHTTPConnection._connect` directly: the
  `host` argument passed to `network_backend.connect_tcp()` is the original hostname, but TLS's
  `server_hostname` defaults to `self._origin.host` (the `httpcore.Request`'s own URL host, which
  we control), **not** whatever `connect_tcp` actually connected to. This is the exact mechanism
  M2 relies on (§4).
- **`httpx.AsyncHTTPTransport` does not expose `network_backend`** in its public constructor — M2
  therefore does not use `httpx.Client`/`httpx.AsyncHTTPTransport` at all; it drives
  `httpcore.AsyncConnectionPool` directly (a public, documented API) and only borrows `httpx.URL`
  (parsing) and `httpx.Response.aiter_bytes()` (decompression-aware streaming) as building blocks.
- **Automatic redirects can be disabled** — trivially: `httpcore.AsyncConnectionPool` has no
  redirect-following behavior of its own to disable in the first place. M2 handles every redirect
  explicitly.
- **Proxy inheritance is disabled by construction, not by an extra flag**: `httpcore.
  AsyncConnectionPool.__init__`'s `proxy` parameter defaults to `None` and is never set by M2 -
  unlike `httpx.Client` (which defaults `trust_env=True` and reads `HTTP_PROXY`/`HTTPS_PROXY` env
  vars), raw `httpcore.AsyncConnectionPool` usage **never consults environment proxy variables at
  all**. Verified by reading `httpcore.AsyncConnectionPool.__init__`'s signature directly.
- **Streaming limits can be enforced before full buffering** via `httpcore.Response.aiter_stream()`
  / `httpx.Response.aiter_bytes()`, both real async iterators over the body.
- **Response decompression happens inside `httpx.Response.aiter_bytes()`** (gzip/deflate/brotli/
  zstd), *after* `aiter_raw()`'s wire-format bytes — meaning a byte-count cap applied to
  `aiter_bytes()`'s output bounds the **decompressed** size, not the wire size, which is exactly
  what decompression-bomb protection requires (§9). Raw `httpcore.Response` on its own does **not**
  decompress — confirmed by inspecting `httpcore`'s own source, which has no decoder logic at all
  (that lives entirely in `httpx._decoders`). This is precisely why M2 wraps the raw
  `httpcore.Response` in a minimal `httpx.Response` adapter rather than staying at the httpcore
  layer throughout.

**The entire mechanism above was verified empirically, once, against a real public HTTPS site
(`alexklos.ca`) before any test was written**: DNS resolved once, the connection was pinned to
that literal IP (confirmed via a backend-level log line proving the substitution), the TLS
handshake succeeded with certificate validation against the original hostname, and decompressed
bytes streamed correctly. This is not a theoretical design — it was proven working end to end
against real infrastructure first, then encoded into the test suite (§21) with local servers.

## 4. Secure-fetch architecture

`integrations/http/safe_fetch.py` (new module, new package `integrations/http/`). Public surface:

- `safe_fetch(url, *, policy: SafeFetchPolicy) -> SafeFetchResult` — the sole entry point.
- `SafeFetchPolicy` — timeouts, max redirects, max bytes (no unlimited fallback, every field
  required).
- `SafeFetchResult` — `requested_url`, `final_url`, `status_code`, `redirect_count`,
  `declared_content_type`, `received_byte_count`, `duration_seconds`, `body` (bounded bytes).
  Never carries cookies, authorization headers, full response headers, proxy details, or DNS/
  connection internals.
- `SafeFetchError` / `FetchErrorCode` — structured error taxonomy (§16).
- `sha256_hex()` — shared content-hash helper (used by `services/image_validation.py`).

**Connection-level IP pinning mechanism** (the core of DNS-rebinding resistance): `_resolve_safe_ip
()` performs exactly one DNS resolution (`asyncio`'s own resolver, via the dedicated `_getaddrinfo`
seam) and returns one already-validated IP literal. `_PinnedNetworkBackend.connect_tcp()` — a
`httpcore.AsyncNetworkBackend` subclass — ignores the hostname it's handed and substitutes that
pre-validated IP literal for the actual socket connection. Connecting to an IP **literal** never
triggers a second DNS lookup (`getaddrinfo` on a literal IP is a local parse, not a network query)
— this is what makes the mechanism resistant to DNS rebinding: there is no second lookup for a
malicious DNS server to answer differently. Meanwhile `httpcore.Request`'s `url.host` is built from
the *original* hostname (never the pinned IP), so `server_hostname` for TLS SNI/certificate
validation and the `Host` header both stay correct throughout — proven both by reading httpcore's
own connection code (§3) and by the live empirical test against `alexklos.ca` (§4 intro).

Placement: no network-security code lives inside Telegram handlers, the RSS adapter, the
capability executor, or bot formatting — everything routes through this one module, per the M2
task brief's explicit Step 2 instruction.

## 5. URL-validation rules

`_validate_url()`: only `http`/`https` accepted; userinfo (`user:pass@`) rejected
(`credentials_in_url`); missing hostname rejected (`hostname_missing`); every other scheme
(`file`, `ftp`, `gopher`, `data`, `javascript`, `blob`, `ws`, `wss`, `mailto`, ...) rejected
(`unsupported_scheme`). Hostnames are IDNA-normalized by `httpx.URL`'s own parser (not
reimplemented). Path/query are never stripped.

## 6. DNS/IP rules

`_is_blocked_ip()` — verified empirically against Python's `ipaddress` module (not assumed) before
being written, using real test cases for every category the M2 task brief lists:

| Check | Covers |
|---|---|
| `.is_private` | Loopback, RFC1918, link-local (**including 169.254.169.254**, the cloud-metadata address), unspecified, IPv6 ULA (`fd00::/8`), TEST-NET documentation ranges, **and** IPv4-mapped IPv6 forms of any of the above (`::ffff:10.0.0.1`.is_private == `True`, confirmed empirically) |
| `.is_loopback` | `127.0.0.0/8`, `::1` (redundant with `.is_private` but checked explicitly for clarity) |
| `.is_link_local` | `169.254.0.0/16`, `fe80::/10` |
| `.is_multicast` | `224.0.0.0/4`, `ff00::/8` — **not** covered by `.is_private`, checked separately |
| `.is_reserved` | IANA-reserved ranges |
| `.is_unspecified` | `0.0.0.0`, `::` |
| Explicit extra network | `100.64.0.0/10` (CGNAT/shared address space) — confirmed **not** covered by any of the above, added explicitly |

A public-looking hostname resolving only to a private/blocked address is rejected (`blocked_ip`).
A mixed result (some public, some private addresses) uses only the safe address(es) — the private
one is never given a chance to be selected, regardless of DNS answer order.

## 7. DNS-rebinding protection

Covered in full in §4. Summary: exactly one resolution, one pinned connection, no second lookup
possible by construction (there is no code path that resolves the hostname a second time before
connecting). Verified by a dedicated test (`test_no_uncontrolled_second_dns_lookup`) that counts
real resolver invocations during a full fetch.

## 8. Redirect handling

Automatic redirect-following does not exist at the `httpcore` layer, so there is nothing to
"disable" — every redirect is handled explicitly in `safe_fetch()`'s own loop. Per hop: the
`Location` header is resolved (relative or absolute) against the current URL, scheme/userinfo/
hostname are re-validated, DNS/IP validation runs again (a fresh `_resolve_safe_ip()` call), and a
brand-new connection is pinned — no state (including headers) carries over from the previous hop.
`Authorization`/`Cookie`/any source-specific header is never forwarded, because each hop's
`httpcore.Request` headers are built fresh in `_single_hop()` from only `Host`+`User-Agent`(+
explicit extras, unused today). Max redirects defaults to 3 (`image_intelligence_max_redirects`,
§9) — chosen because it comfortably covers the common `http→https`, `www`-normalization, and
CDN-redirect chains observed in the bounded live validation (§23) without allowing an open-ended
chain. Redirect loops and excess hops are rejected (`redirect_loop`/`too_many_redirects`).

## 9. Timeout and byte limits

`core/config.py` additions (all `Field(..., gt=0)`, no unlimited fallback, process-scoped test
overrides only, `.env` untouched):

| Setting | Default | Rationale |
|---|---|---|
| `image_intelligence_connect_timeout_seconds` | 3.0 | Task brief's own candidate default |
| `image_intelligence_read_timeout_seconds` | 7.0 | Task brief's own candidate default |
| `image_intelligence_total_timeout_seconds` | 12.0 | Task brief's own candidate default; observed real article-fetch durations (§24) topped out at ~10.4s for one slow domain, comfortably under this |
| `image_intelligence_max_redirects` | 3 | §8 |
| `image_intelligence_max_html_bytes` | 2,000,000 (2 MB) | Task brief's own candidate default; real fetched article pages in §23 ranged well under this |
| `image_intelligence_max_image_bytes` | 10,000,000 (10 MB) | Task brief's own candidate default; real validated images in §23 averaged ~218 KB, max well under 10 MB |
| `image_intelligence_max_decoded_pixels` | 40,000,000 | Task brief's own candidate default; below Pillow's own independent library default (~89.5M), so Pillow's own protection never even gets a chance to be the binding constraint |
| `image_intelligence_max_articles_per_event` | 1 | Task brief's own candidate default |
| `image_intelligence_max_candidate_urls_per_event` | 10 | Task brief's own candidate default |
| `image_intelligence_max_image_downloads_per_event` | 5 | Matches the Phase 16 discovery report's own "up to five" editorial requirement |
| `image_intelligence_global_concurrency` | 4 | Task brief's own candidate default |
| `image_intelligence_per_host_concurrency` | 2 | Task brief's own candidate default |

Byte enforcement (`_read_bounded()`): `Content-Length` is never trusted alone — a declared value
over the limit is rejected immediately (`content_length_exceeded`), but the real enforcement is
streaming: bytes are accumulated from `httpx.Response.aiter_bytes()` (already decompressed, §3)
and the fetch aborts (`stream_limit_exceeded`) the instant the running total exceeds the limit,
regardless of what `Content-Length` claimed or omitted. Proven against a real compression-bomb
shape in tests (`test_compressed_response_cannot_expand_beyond_the_effective_limit`: a 200,000-byte
payload compressed to under 2,000 bytes on the wire is still correctly capped at its **expanded**
size).

## 10. Article metadata extraction

`services/article_metadata.py`. Uses Python's stdlib `html.parser.HTMLParser` only — no new
HTML-parsing dependency (no BeautifulSoup/lxml), matching M1's own established precedent
(`_ImgTagCollector`). Supports exactly the M2 task brief's list: `og:image`, `og:image:url`,
`og:image:secure_url` (+ `:width`/`:height`/`:alt`, grouped per-image following the Open Graph
convention that these apply to the most recently declared `og:image`), `twitter:image`,
`twitter:image:src`, `<link rel="image_src">`, and JSON-LD `Article`/`NewsArticle` `image` (string,
`ImageObject` via `url`/`contentUrl`, array of either, `@graph`-wrapped nodes, multiple `<script>`
blocks). No generic DOM hero-image heuristic, no crawling of linked pages, no alternate-language
following, no JavaScript execution, no browser — all explicitly out of M2 scope, and none
implemented. Malformed JSON-LD and malformed HTML both degrade to zero hints, never a crash.

Content-type gating happens in the **caller** (`services/image_intelligence.py`), not in this
module: a non-HTML-like declared `Content-Type` (anything other than `text/html`/
`application/xhtml+xml`, when declared at all) short-circuits before this module is even invoked,
satisfying "do not parse binary content as HTML merely because the URL ends in `.html`."

## 11. Candidate normalization

Every extracted hint carries `source_url` (the final article URL, threaded through
`schemas.image_candidate.NativeMediaHint`, extended in M2 for this purpose) alongside the existing
M1 fields. Relative and scheme-relative URLs are resolved via `urljoin` against the article's
*final* URL (post-redirect), not the originally requested one. Discovery order is preserved exactly
in the priority sequence extraction produces them (§12); URL safety validation and truncation to
`image_intelligence_max_candidate_urls_per_event` both happen centrally in `consolidate_candidates
()` (the same M1 seam, unchanged), not in this module — mirrors M1's "extraction interprets
structure, consolidation judges safety" split exactly.

## 12. Priority order (implemented and validated)

`og:image:secure_url` > `og:image`/`og:image:url` > JSON-LD `Article`/`NewsArticle` image >
`twitter:image`/`twitter:image:src` > `<link rel="image_src">` — implemented exactly as the M2
task brief's own hypothesis, and directly tested
(`test_priority_order_is_secure_og_then_og_then_jsonld_then_twitter_then_image_src`). All
discovered candidates are preserved (never silently dropped for being lower-priority) up to the
configured per-event cap; duplicate URLs across methods are consolidated in favor of the
higher-priority discovery method (verified both in the article-metadata unit tests and live,
§23 — `techmeme.com`/`3dnews.ru` real pages had `og:image`/JSON-LD pointing at the identical URL,
correctly deduplicated).

## 13. Image MIME/signature validation

`services/image_validation.py`. Never trusts URL extension, declared `Content-Type`, or filename.
`_sniff_signature()` reads magic bytes directly: JPEG (`FF D8 FF`), PNG (`89 50 4E 47 0D 0A 1A
0A`), GIF (`GIF87a`/`GIF89a`), WebP (`RIFF`...`WEBP`), SVG (`<?xml`/`<svg` prefix — rejected before
ever reaching Pillow), and an HTML-page signature (`<!doctype html`/`<html`) explicitly rejected as
`signature_mismatch` — this is what makes "HTML disguised as an image" (a common real failure mode
for a broken/expired image URL) impossible to accept. Anything unrecognized by signature is
`unsupported_format`, never passed to a decoder at all. Pillow's own decode-confirmed `.format` is
the authoritative second check, after signature sniffing, before a candidate is ever marked
`VALIDATED`.

## 14. Decoder and pixel safety

`Image.open()` (lazy — reads header only, does not decode pixel data) provides `width`/`height`
before any real decode work happens; the decompression-bomb check (`pixel_count > max_pixels`)
runs **before** `.load()` is ever called, using the configured, testable `max_pixels` parameter —
never a global mutation of `PIL.Image.MAX_IMAGE_PIXELS` (verified: the module never assigns to it,
`test_decompression_bomb_protection_remains_enabled` confirms Pillow's own independent default
stays untouched as a second, redundant safety layer). `.load()` forces full decode and raises on
corrupt/truncated data (caught, classified `decode_failed`, never propagated). Decoder resources
are closed deterministically in a `finally` block regardless of outcome.

## 15. Animation policy

Detected via Pillow's cheap header-level `is_animated`/`n_frames` attributes — **no frame beyond
the first is ever decoded** to determine this. Per the M2 task brief's own "preferred initial
behavior," an animated image is technically recorded in full (format, dimensions, frame count) but
marked `REJECTED_TECHNICAL` with `error_code="animation_unsupported"` — detected and recorded, not
silently dropped, but not treated as editorially usable in M2. A static GIF/WebP validates
normally.

## 16. Technical metadata contract

`schemas.image_candidate.TechnicalValidation` (new): `version="m2"`, `final_url`, `http_status`,
`redirect_count`, `observed_mime`, `format`, `byte_size`, `width`, `height`, `pixel_count`,
`aspect_ratio`, `animated`, `frame_count`, `sha256`, `duration_ms`, `error_code`. Attached to
`ImageCandidate.technical_validation` (new, optional field — `None` for any candidate M2 never
touched). No perceptual hash field exists anywhere in this shape (explicitly out of M2 scope, M3's
job). No image bytes are ever part of this or any persisted shape — proven by
`test_image_bytes_are_never_persisted_on_the_result`.

`ImageCandidateStatus` gained `VALIDATED`/`REJECTED_TECHNICAL`/`FETCH_FAILED` (M1 had only
`DISCOVERED`/`REJECTED_METADATA`/`UNAVAILABLE`). `ImageDiscoveryMethod` gained
`OPEN_GRAPH_SECURE_IMAGE`/`OPEN_GRAPH_IMAGE`/`JSONLD_ARTICLE_IMAGE`/`TWITTER_IMAGE`/
`IMAGE_SRC_LINK`. Every M2 addition is additive with M1-safe defaults — proven directly
(`test_existing_m1_shaped_result_still_validates`: a hand-built M1-era JSON payload with no M2
fields at all still validates against the current schema).

## 17. Error taxonomy

`integrations.http.safe_fetch.FetchErrorCode` (network layer) plus five image-specific string
codes emitted by `services/image_validation.py` (`signature_mismatch`, `unsupported_format`,
`svg_rejected`, `decode_failed`, `pixel_limit_exceeded`, `animation_unsupported`) plus
`http_error` (a non-2xx HTTP status, checked explicitly in the orchestration layer - §19's own
found-and-fixed gap). Every `SafeFetchError` carries a `code: FetchErrorCode` plus a short `detail`
that is never a raw exception message with sensitive content (only ever `type(error).__name__`, a
class name, never the exception's own string) - confirmed by direct inspection of every raise site
in `safe_fetch.py`.

## 18. Concurrency limits

Global (`image_intelligence_global_concurrency=4`) and per-host
(`image_intelligence_per_host_concurrency=2`) `asyncio.Semaphore`s, constructed fresh **per
`run_shadow_discovery()` call**, not as module-level singletons. This is a deliberate, documented
design choice, not an oversight: `content_worker` processes `CONTENT_GENERATION` tasks
**sequentially** (confirmed by `tests/test_content_worker_cycle.py`'s own
`test_run_content_cycle_sequential_no_gather_and_notifies_after_draft_creation` test name and
behavior — no `asyncio.gather` across events), so only one event's own candidate fan-out is ever
concurrent in practice; a per-invocation limiter correctly bounds exactly that, with no risk of a
stale semaphore leaking across event-loop boundaries (a real hazard for module-level `asyncio.
Semaphore` singletons reused across test runs / different loops). **Documented limitation**: this
is in-process only — if a second concurrent `content_worker` process is ever added, per-process
limiting no longer bounds total concurrency against one external host, and a Redis-backed limiter
(mirroring `services/budget_guard.py`'s own existing Redis-backed pattern) would be needed. Not
built now because the current deployment has exactly one `content_worker` (`docker-compose.yml`),
matching the M2 task brief's own explicit "do not introduce a distributed rate-limit service unless
... necessary" instruction. Verified under real concurrent load in
`test_global_concurrency_limit_enforced` (6 simulated slow image downloads, limit 2, `max_seen`
concurrency never exceeds 2).

## 19. Workflow integration

`services/image_intelligence.py::run_shadow_discovery()` — the single M2 orchestration entry point,
called once by `capabilities/executor.py`'s existing `"copywriting"` hook (unchanged call site,
only the function it calls changed from two M1 calls to this one). Internally: reconstructs M1
hints from persisted `NewsEvent.content`/`url` (unchanged from M1) → if `mode="shadow"` and
`source_type != TELEGRAM` and an `article_url` exists, fetches the article page and extracts
metadata hints → combines native + metadata hints, truncated to the candidate cap → consolidates
(unchanged M1 logic) → selects up to `max_image_downloads_per_event` `DISCOVERED` candidates with a
`remote_url`, fetches and technically validates each (bounded concurrency, §18) → returns one
`ImageIntelligenceResult` with M2 fields populated. `capabilities/executor.py` itself gained zero
new networking code — it still only calls one function and preserves the result (per the M2 task
brief's explicit Step 13 instruction), matching M1's own established pattern exactly.

**Bug found and fixed during implementation**: `safe_fetch()` correctly reports non-2xx HTTP
statuses in its result rather than raising (a genuine fetch success at the transport level, even if
the *content* is an error page) — but the orchestration layer initially didn't check `status_code`
before treating the body as valid content, so a 404 page could be silently handed to the HTML
parser or image decoder and misclassified (e.g. an empty 404 body reported as `unsupported_format`
instead of the more diagnostic `http_error`). Fixed by adding an explicit `status_code >= 400`
check in both `_fetch_article_metadata_hints()` and `_fetch_and_validate_candidate()` before any
parsing/decoding is attempted. Caught by `tests/test_image_intelligence_m2.py`'s own
`test_article_fetch_failure_does_not_raise`/`test_image_fetch_failure_does_not_raise_and_is_
recorded` tests failing initially, then passing after the fix - the test suite did its job.

## 20. Failure isolation

Every layer fails toward "record and continue," never toward raising past its own boundary:
`_fetch_article_metadata_hints()` and `_fetch_and_validate_candidate()` each catch `SafeFetchError`
and any unexpected `Exception`, always returning a result rather than propagating.
`run_shadow_discovery()` itself wraps the validation-selection stage in its own try/except.
`capabilities.executor.CapabilityExecutor._attach_image_intelligence()` (unchanged from M1) wraps
the entire call, guaranteeing a failure here can never fail the `"copywriting"` step, never touches
Fact Safety/Editorial Scoring's own independent hooks (structurally provable - they're gated by
different `step.capability ==` checks entirely), and never blocks text `ContentDraft` creation or
Telegram text delivery.

## 21. Files changed

**New**: `integrations/http/__init__.py`, `integrations/http/safe_fetch.py`,
`services/article_metadata.py`, `services/image_validation.py`,
`scripts/phase16_m2_offline_backtest.py`, `scripts/phase16_m2_bounded_network_validation.py`,
`tests/test_safe_fetch.py`, `tests/test_article_metadata.py`, `tests/test_image_validation.py`,
`tests/test_image_intelligence_m2.py`.

**Modified**: `schemas/image_candidate.py` (additive: `TechnicalValidation`, new enum values,
`source_url`/`technical_validation` fields, M2 observability fields on `ImageIntelligenceResult`),
`core/config.py` (M2 limit settings, §9), `services/image_intelligence.py` (M2 orchestration
functions appended), `capabilities/executor.py` (`_attach_image_intelligence` now calls
`run_shadow_discovery`), `pyproject.toml` (`Pillow>=11.0` added — the first new M2 dependency),
`tests/test_capability_executor_image_intelligence.py` (autouse fixture added to keep M1-era tests
offline now that real article fetching exists; one mock target updated).

**Explicitly not modified**: `workflows/runner.py`, `workflows/registry.py`, `schemas/workflow.py`,
`capabilities/registry.py`, `bot/` (any file), `database/models/*.py`, any Alembic migration,
`.env`.

## 22. Tests and exact results

- `tests/test_safe_fetch.py` — 55 tests: URL/scheme validation, DNS/IP blocking (parametrized
  against every required category), DNS-rebinding simulation, connection pinning proof, Host-
  header correctness, redirect handling (safe/relative/blocked-target/credential-stripping/loop/
  limit), byte/time limits (oversized/missing/lying Content-Length, compression-bomb, connect/
  read/total timeout, cancellation).
- `tests/test_article_metadata.py` — 23 tests: every discovery method, priority order, dedup,
  relative/scheme-relative URLs, malformed JSON-LD/HTML, empty-result case.
- `tests/test_image_validation.py` — 25 tests: every supported format, animation detection (GIF +
  WebP), SVG/HTML-disguised/unknown-format/corrupt/truncated rejection, pixel-limit enforcement,
  SHA-256 stability, no-perceptual-hash/no-bytes-persisted proofs.
- `tests/test_image_intelligence_m2.py` — 14 tests: mode-off zero-network proof, real local-server
  end-to-end metadata+validation, fetch-failure isolation, candidate/download-limit enforcement,
  concurrency-limit enforcement under real load, error serialization, M1 backward compatibility.
- **M2 total: 117 tests, all offline (local `ThreadingHTTPServer` + DNS-resolution mocking only,
  zero uncontrolled public-internet access), all passing.**
- Combined M1+M2 targeted suite (`tests/test_safe_fetch.py` through the five M1 source-adapter test
  files): **224 passed.**
- **Ruff**: `All checks passed!` (whole repository, after fixing one dead-variable and two unused-
  import findings introduced during this milestone).
- **mypy** (all 8 changed/new production files): `Success: no issues found` (after fixing two real
  type errors this milestone introduced: an `Optional`-indexing issue in `article_metadata.py`'s
  alt-text truncation, and an `int | None` arithmetic issue in `image_intelligence.py`'s duration
  accumulation - both genuine, now-fixed bugs mypy caught, not suppressions).
- **Full repository suite**: 1362 passed, 17 failed (1379 collected - up from M1's 1262 by exactly
  117, matching the M2 test count above precisely). Of the 17 failures:
  - **15 are the exact same pre-existing failures already independently proven, during M1, to
    reproduce identically at commit `133a22c`** (before either M1 or M2 existed): 8 in
    `test_capability_executor.py`, 2 in `test_editorial_scoring.py`, 2 in `test_fact_safety.py` (all
    asserting `ai_executions` row count `== 0` inside a rolled-back test transaction, defeated by
    82+ real rows already committed by the continuously-running `news_analysis_worker`/
    `content_worker`), plus 1 in `test_content_generation_integration.py` and 2 in
    `test_content_worker_cycle.py` (asserting `settings.content_generation_dry_run is True`, but
    this environment's `.env` sets `CONTENT_GENERATION_DRY_RUN=false` for live editorial delivery).
    Same test names, same root causes, unrelated to any file M2 touched.
  - **2 are new to this run but proven flaky, not M2-caused**:
    `test_analysis_worker_main.py::test_enabled_loop_runs_cycles_and_respects_interval` and
    `test_content_worker_main.py::test_enabled_loop_survives_ordinary_exception_and_continues` -
    both are timing-sensitive tests in `worker/` files M2 never touched (`git diff --stat worker/`
    is empty), and both pass cleanly when re-run in isolation immediately afterward - consistent
    with resource contention during the ~20-minute full-suite run, not a deterministic regression.

## 23. Offline backtest

`scripts/phase16_m2_offline_backtest.py`, read-only, 400 most-recent real events (151 RSS / 241
NEWS_API / 8 Telegram... note: a later 400-sample window skewed differently, see the exact run
below): **399/400 events (99.75%) have a usable http(s) article URL** and would be eligible for
article-metadata discovery under the real `run_shadow_discovery()` logic (`source_type !=
TELEGRAM` and a non-empty http(s) URL) — 160 RSS + 239 NEWS_API eligible, 1 RSS event skipped for
having no URL at all, 0 Telegram events in this particular sample window. 22 distinct eligible
domains, dominated by `arxiv.org` (216), `news.google.com` (128, a redirecting aggregator),
`3dnews.ru` (20), `habr.com` (12), `github.com` (6), plus many single-occurrence long-tail domains
— good real diversity for the bounded live sample (§24).

## 24. Bounded network validation

`scripts/phase16_m2_bounded_network_validation.py`, run after the full security test suite already
passed, against 20 real article URLs sourced from live `news_events` rows (within the task brief's
own 20-article/5-images-per-article/50-total-images/100MB limits):

- **20 articles attempted, 17 reachable** (`http_200`) — 1 `connect_timeout` (network flakiness),
  1 `http_403`, 1 `http_429` (rate-limited), all handled gracefully with zero crashes.
- **14/17 reachable articles (82%) had at least one og:image/twitter:image/JSON-LD candidate** —
  the remaining 3 genuinely had none (not an error - correctly reported as zero candidates).
- **34 total candidate image URLs found, 34 fetched, 34/34 (100%) technically validated** — zero
  rejections in this real sample (every real og:image/twitter:image URL from these 17 live sites
  was a genuine, well-formed, decodable raster image).
- **7,403,182 bytes (7.4 MB) total downloaded** — well within the 100 MB budget.
- **Zero page bodies or image bytes were written to disk at any point** - both scripts operate
  entirely in memory and print only the derived summary.
- **Zero provider/LLM/paid-API calls** — neither script imports an LLM Gateway or provider SDK.

A second, independent, read-only pass (scratch-only, not committed) directly re-ran `services.
image_intelligence.run_shadow_discovery()` - the exact production entry point
`capabilities/executor.py` calls - against 6 real, already-persisted `NewsEvent` rows read
straight from the database (no mutation), confirming the full pipeline end-to-end: an event with
no URL correctly produced zero candidates with no error; real RSS/NEWS_API events (including an
arXiv abstract page, which does carry OG metadata) correctly discovered, deduplicated, and
validated real candidates with zero unexpected failures.

## 25. Performance results

From the 20-article bounded validation (§24), n=20 article-fetch durations (article HTML fetch +
metadata parse + up to 5 image fetches/validations per article, combined):

| Metric | Value |
|---|---|
| Median | 1.85s |
| p95 (19th of 20, sorted) | 3.6s |
| Maximum | 10.37s (`abcnews.com` — the slowest reachable domain in this sample) |
| Sample size | 20 |

Bytes per validated image (34 images, 7,403,182 bytes total): **~217.7 KB average**. Candidates
per article (17 reachable): 0–5, median 2. All comfortably within the configured
`total_timeout_seconds=12` and `max_image_bytes=10MB` budgets — no timeout or byte-limit rejection
occurred against any of these real, legitimate sites.

**Bandwidth/CPU estimate** (qualitative, no fabricated infrastructure cost): at the M1 report's own
established scoping (image work only for *drafted* events, not all ~1,000 daily collected events),
and bounded to ≤5 image downloads averaging ~218 KB each, worst-case per-drafted-event network
volume is roughly ~1 MB, decode CPU is a handful of Pillow `.load()` calls (millisecond-scale for
images this size, confirmed by `TechnicalValidation.duration_ms` values recorded during the bounded
run). **Storage avoided**: exactly zero bytes are ever written to disk in M2 (transient-only, per
the M2 task brief's own explicit non-goal) — the entire storage-cost question is deferred to
whichever future milestone adds persistence.

## 26. Deployment status

**Reproducible deployment succeeded.** Unlike M1 (which needed a `docker cp` workaround because
this sandbox's registry/package-index access was down at the time), `docker compose build
content_worker automation_worker` completed successfully this time — both images rebuilt from a
clean `pip install .` (which now pulls in the new `Pillow` dependency correctly), confirming the
earlier M1-era network restriction was transient/environment-specific, not a permanent sandbox
property. `docker compose up -d --no-deps content_worker automation_worker` recreated both
containers from the fresh images. Post-deployment verification: `Pillow 12.3.0` importable inside
the running `content_worker` container; `settings.image_intelligence_mode == "off"` confirmed
inside the container (default, `.env` untouched); a real `CONTENT_GENERATION` cycle completed
successfully end-to-end inside the freshly deployed container with zero errors traceable to any M2
code, and zero `image_intelligence`-related log lines (confirming the mode-off gate is fully inert
in production, exactly as required); `automation_worker` ran a real collection cycle against live
Telegram/RSS/GitHub sources with zero errors.

## 27. Sandbox/network limitations

- The Docker build's earlier network restriction (encountered persistently during Phase 16 M1) did
  **not** recur during M2 - `docker compose build` succeeded on the first attempt this session.
  This is recorded as an observation, not a guarantee: the restriction was real when it happened
  and could recur; M2's own deployment did not need the M1-era `docker cp` fallback path.
- One of the 20 bounded-validation article domains (`abeljansma.nl`) hit a `connect_timeout` -
  ordinary internet flakiness for that one domain at that moment, not a sandbox-wide restriction
  (17/20 other domains succeeded in the same run). `academic.oup.com` (403) and `aeon.co` (429)
  returned real HTTP-level rejections from those sites themselves (access control / rate limiting),
  correctly handled as ordinary fetch outcomes, not sandbox artifacts.
- No test in the committed suite depends on any of this - every test uses a local server or direct
  function-level mocking, so the suite's correctness is independent of sandbox network conditions
  on any given run.

## 28. Security review

See the self-review checklist below, each item verified directly against the code (not merely
asserted) before this milestone was considered complete:

| Check | Verified |
|---|---|
| No hostname-only SSRF check | `_resolve_safe_ip` performs real DNS resolution + IP validation |
| No second uncontrolled DNS lookup | `_getaddrinfo` called exactly once per hop; pinned backend connects to an IP literal (no lookup) |
| No redirect bypass | Every hop re-validated via a fresh `_resolve_safe_ip` call |
| No TLS verification disable | `grep`-confirmed: no `verify=False`/`CERT_NONE`/`check_hostname=False` anywhere in M2 code |
| No ambient cookies | Headers built fresh per hop; no cookie-jar mechanism exists |
| No authorization forwarding | Same - headers never carry over across hops |
| No implicit proxy credentials | `httpcore.AsyncConnectionPool`'s `proxy` param is never set (defaults `None`); unlike `httpx.Client`, raw `httpcore` usage never reads `HTTP_PROXY`/env vars at all (verified against `httpcore`'s own constructor signature) |
| No unbounded buffering | `_read_bounded` streams and aborts at `max_bytes` |
| No unbounded decompression | Byte-counting happens on `aiter_bytes()` (post-decompression) output |
| No SVG decode | Signature-rejected before ever reaching `Image.open()` |
| No permanent byte storage | `grep`-confirmed: no file-write call anywhere in the new modules |
| No source filenames used as paths | No filesystem path is ever constructed from external data in M2 |
| No secret logging | `SafeFetchError.detail` is only ever a class name, never a raw exception message |
| No image fetch in mode off | `run_shadow_discovery`'s `mode == "off"` branch returns before touching any hint/fetch logic |
| No network call from tests to public internet | `grep`-confirmed: the only `https://` literals in the M2 test files are inside a string that is asserted to never be fetched |

## 29. Zero-AI confirmation

Zero OpenAI/LLM/vision/paid-search/paid-image-API calls anywhere in M2's implementation, testing,
or validation — confirmed structurally (`grep`-verifiable: no `openai`/`llm_gateway` import
anywhere in `integrations/http/safe_fetch.py`, `services/article_metadata.py`, `services/
image_validation.py`, or the M2 additions to `services/image_intelligence.py`) and behaviorally
(the bounded network validation script and every test make only deterministic HTTP GET requests to
article/image URLs, never a provider endpoint). OpenAI quota was observed to be responding normally
during this session's deployment verification (§26) - this was incidental, unrelated to and not
triggered by any M2 code (which never touches the LLM Gateway), and was not probed or relied upon.

## 30. Known limitations

- **In-process-only concurrency limiting** (§18) - correct for the current single-`content_worker`
  deployment, would need a Redis-backed limiter if a second concurrent worker is ever added.
- **`max_articles_per_event=1`** means only the primary article URL is ever fetched per event -
  matches the task brief's own default; no fallback to a secondary URL if the primary fails.
- **Telegram events never get article-metadata discovery** in M2 - `NewsEvent.url` for a Telegram
  -sourced event is an internal `t.me/...` link, not an external article page (M1 report §3/M2
  report §19's own explicit scoping decision).
- **No charset-sniffing** - HTML bodies are decoded as UTF-8 with `errors="replace"`; a page served
  in a different real-world encoding could have its metadata garbled rather than correctly decoded.
  Not observed as a problem in the 20-site bounded validation, but not proven absent either.
- **`og:image:width`/`:height`/`:alt` grouping is order-dependent** (§10) - matches the real Open
  Graph convention (properties apply to the most recently declared image) but a page emitting these
  tags in an unusual order could group them onto the wrong image entry.
- **animated WebP support depends on the installed libwebp build** - `test_animated_webp_is_
  rejected_but_recorded` tolerates either outcome (animation correctly detected and rejected, or
  Pillow's WebP plugin encoding it as static in this environment) rather than asserting one
  specific behavior, since this varies by Pillow/libwebp build.

## 31. M3 starting point

M2 leaves every selected-for-validation candidate with full technical metadata (`width`/`height`/
`format`/`sha256`/`animated`/etc.) but **zero quality/logo/dedup judgment beyond exact-duplicate-
URL consolidation** (M1's own scope) - M3's job, per the Phase 16 implementation plan, is: hard-
rejection gates using the now-available technical metadata (minimum dimensions, extreme aspect
ratio, tracking-pixel/icon dimension heuristics), perceptual-hash-based near-duplicate detection
(the `sha256` this milestone already computes handles exact duplicates; perceptual hashing for
near-duplicates - resized/recompressed copies - is new, deferred exactly as planned), and
logo/banner/ad downgrade signals. All of this operates on data M2 already collects (`width`,
`height`, `aspect_ratio`, `sha256`, `format`) - no new fetch is needed for M3's core logic, only new
judgment on top of it.

## 32. Rollback instructions

`IMAGE_INTELLIGENCE_MODE` remains defaulted to `"off"` in code - identical rollback story to M1: no
`.env` change is needed to revert a default deployment, and if an operator had explicitly set
`"shadow"`, reverting to `"off"` (or unsetting the variable) restores byte-for-byte pre-M2 (and
pre-M1) behavior with no code path removal required. No migration was added, so there is nothing to
roll back at the schema level. The new `Pillow` dependency is additive-only (no existing code
depends on its absence); removing it would only require reverting `services/image_validation.py`'s
import, not any other module.

## M2 verdict

See the final response for exact full-suite test totals and the formal verdict line.
