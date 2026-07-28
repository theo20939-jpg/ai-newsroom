# Phase 16 — Image Intelligence — M0 Discovery Report

Status: DISCOVERY ONLY. No production code was changed to produce this report. All findings
below are backed by direct repository inspection (file:line citations), a read-only PostgreSQL
audit against the live `ai_newsroom` database, and a bounded, read-only sample of 10 real article
URLs drawn from live `news_events` rows. Nothing here was inferred from prior-phase documentation
without being re-verified against current code, per the M0 task brief's "verify all state rather
than assuming it" instruction.

---

## 1. Executive summary

Image Intelligence has **no existing foundation** anywhere in this codebase: no schema field, no
HTTP fetch of article pages, no image library, no object storage, and no SSRF protection. Three
assumptions in the original M0 task brief turned out to be wrong and are corrected here before
anything else, because they materially change the Phase 16 design:

1. **Telegram collection uses Telethon (MTProto Client API), not aiogram/Bot API.**
   `integrations/sources/telegram_source.py` is a `TelegramSourceAdapter` built on `telethon`,
   entirely separate from `bot/` (aiogram, `TELEGRAM_BOT_TOKEN`), which only handles *outbound*
   editorial delivery (`/news`, push notifications). Bot API vocabulary (`file_id`,
   `file_unique_id`, `getFile`) does not apply to the collection path at all — Telethon has its
   own, different media-access model (§4).
2. **`SourceType.NEWS_API` is not one third-party "News API" integration** — it is a category
   covering three independent, unrelated adapters: `GitHubSourceAdapter` (GitHub Releases REST
   API), `HackerNewsSourceAdapter` (HN Firebase API), and `ArxivSourceAdapter` (arXiv Atom API).
   None of the three has, or has ever had, a dedicated article-image field to discard (§5).
3. **`RawNewsItem` (`schemas/raw_news_item.py`) has zero media fields, full stop.** This is the
   single shared contract every adapter must produce. Since it has no slot for image data, "is it
   preserved or discarded" is the wrong question for most of the pipeline — the correct finding is
   "never collected past the adapter's own local scope," verified per source type below.

The one exception is **RSS**: `feedparser` (already a dependency) exposes `media_content`,
`media_thumbnail`, `enclosures`, and raw HTML (including literal `<img>` tags) inside `summary` —
and the adapter reads none of it. This is a genuine "discarded, recoverable without new
dependencies" finding, confirmed live: 22.1% of stored RSS `news_events.content` rows already
contain a literal `<img` substring, dumped in as unparsed HTML.

No credentials were exposed, no rows were mutated, no Telegram messages were sent, and zero
LLM/paid-API calls were made anywhere in this discovery process, consistent with the OpenAI
quota-blocked constraint.

---

## 2. Current architecture (verified)

Pipeline, confirmed by direct code read (not assumed from docs):

```
Telethon (Telegram) ─┐
feedparser+httpx (RSS)─┼─→ SourceAdapter.fetch() → RawNewsItem (schemas/raw_news_item.py)
httpx (GitHub/HN/arXiv)┘         │
                                  ▼
                    services/cleaning.py::clean_item() → CleanedItem (drops text-less items)
                                  │
                                  ▼
                    services/deduplication.py::is_duplicate() (sha256 of source_id+external_id)
                                  │
                                  ▼
                    NewsEvent (database/models/news_event.py) — status=NEW
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                             ▼
        NEWS_ANALYSIS workflow            CONTENT_GENERATION workflow
   (research→intelligence→engagement      (research→intelligence→copywriting→quality)
    →quality→scoring, via LLM Gateway,             │
    EditorialTask.workflow JSON                     ▼
    step_results)                          ContentDraft (title/body/hashtags JSON)
                                                     │
                                                     ▼
                                services/telegram_notifier.py + bot/handlers/news.py
                                  → aiogram Bot.send_message(), HTML text only,
                                    private editorial_chat_id, no public channel
```

Deterministic, non-LLM services are layered onto workflow steps **inside**
`capabilities/executor.py::CapabilityExecutor`, not as separate `Capability` registrations — see
§19 for why this precedent (not the Capability Framework) is the right integration seam for Image
Intelligence.

---

## 3. Existing media path, by pipeline stage

| Stage | Media/image field? | State |
|---|---|---|
| Telethon `Message` object (in-memory, `telegram_source.py:45`) | `.photo`, `.document`, `.grouped_id` all present on the object | **Never read** — discarded the instant `_to_raw_item()` returns |
| feedparser entry (in-memory, `rss_source.py`) | `media_content`, `media_thumbnail`, `enclosures`, inline `<img>` in `summary` all present | **Never read** by the adapter — discarded, but verified recoverable (§6) |
| GitHub Releases JSON / HN Firebase JSON / arXiv Atom entry | No dedicated image field in any of the three upstream APIs as consumed; GitHub release `body` (markdown) may contain `![]()` image syntax as literal text | **Not provided** as a distinct field (GitHub/HN/arXiv); markdown images inside GitHub `body` never extracted |
| `RawNewsItem` (`schemas/raw_news_item.py:7-29`) | — | **No field exists.** 8 fields total, none media-related |
| `CleanedItem` (`services/cleaning.py:37-48`) | — | Same 8-field shape, no media field. **A Telegram post with a photo and no caption is dropped entirely here** (`raw.text is None` → `return None`, `cleaning.py:58-59`) |
| `NewsEvent` (`database/models/news_event.py:36-75`) | — | 17 columns, **no image/media column** |
| `EditorialTask.workflow` (`database/models/editorial_task.py:44`) | JSON column | Holds `WorkflowExecutionState.step_results` — a real, existing JSON slot deterministic services already write into (fact safety, editorial scoring v2) |
| `ContentDraft` (`database/models/content_draft.py:23-48`) | — | 9 columns, **no image/media column** (`hashtags` is JSON but semantically scoped to hashtags) |
| Telegram delivery (`services/telegram_notifier.py:95`, `bot/handlers/news.py:58`) | — | `bot.send_message()` / `message.answer()`, HTML **text only**. No `send_photo`/`send_media_group` call exists anywhere in the repo outside two historical discovery docs (not code) |

---

## 4. Telegram findings

**Collection is Telethon, not aiogram.** `integrations/sources/telegram_source.py:1-6` states this
explicitly in its own docstring: "completely separate from the Telegram Bot API used by `bot/`
... different credentials, different client, no shared imports between the two." `bot/` (aiogram +
`TELEGRAM_BOT_TOKEN`) is outbound-only (editorial inbox, push notifications).

- `TelegramSourceAdapter.fetch()` (`telegram_source.py:38-51`) receives the full Telethon `Message`
  via `client.iter_messages()`, but `_to_raw_item()` (`:68-89`) immediately narrows it to 8 fields:
  `external_id`, `text`, `url`, `published_at`, `views_count`, `forwards_count`, `replies_count`,
  `reactions_count`. `message.photo`, `message.document`, `message.grouped_id` (Telethon's
  `media_group_id` equivalent) are never accessed.
- Repo-wide grep for `media_group_id|file_id|file_unique_id|getFile` returns **zero matches**
  anywhere in the codebase.
- Only filter applied: `if message.action is not None: return None` (service messages — join,
  pin, etc.), unrelated to media.
- Forwarded messages and channel posts are handled uniformly by Telethon (no special-casing
  needed or present). Edited messages are not tracked as edit-events — `iter_messages()` returns
  whatever the message looks like at fetch time.
- **Media groups (albums):** Telethon exposes `message.grouped_id`, but since each message is
  processed independently and this field is never read, **there is no album-to-single-NewsEvent
  grouping logic today.** This is new logic, not an extension of anything existing.
- **Feasibility note for later milestones:** because collection already runs an authenticated
  Telethon *client* session (not the limited Bot API), that same session can call
  `message.download_media()` directly on messages it is already iterating — no separate Bot API
  permission, `file_id`, or `getFile` call is needed to retrieve Telegram-native image bytes later.
  This is materially simpler than the Bot API model the original task brief assumed.
- `bot/keyboards/__init__.py:1` is a one-line reserved package ("reserved for future development
  phases") — **no inline-keyboard or callback-query infrastructure exists** in the outbound bot
  today (§16).
- Outbound delivery (`services/telegram_notifier.py`) is confirmed text-only; `bot/formatting.py`'s
  `render_editorial_card()` builds a single HTML string under Telegram's 4096 UTF-16-unit limit,
  with an existing truncate-and-shrink loop — no image-aware logic anywhere in it.

## 5. RSS findings

`RSSSourceAdapter` (`integrations/sources/rss_source.py`) fetches feed XML with `httpx` and parses
it with `feedparser>=6.0` (`pyproject.toml:15`). Directly verified (not assumed) what fields
`feedparser` exposes, using a synthetic feed containing `media:content`, `media:thumbnail`, an
`enclosure`, and an inline `<img>` in `description`:

```
keys: ['guidislink','href','id','link','links','media_content','media_thumbnail',
       'published','published_parsed','summary','summary_detail','title','title_detail']
media_content:   [{'url': '...media.jpg', 'medium': 'image', 'width': '800', 'height': '600'}]
media_thumbnail: [{'url': '...thumb.jpg'}]
links:           [..., {'type': 'image/jpeg', 'href': '...enc.jpg', 'rel': 'enclosure'}]
enclosures:      [{'type': 'image/jpeg', 'href': '...enc.jpg', 'length': '1000'}]
summary contains img: True
```

`RSSSourceAdapter._to_raw_item()` (`rss_source.py:41-57`) reads only `entry.get("id")`,
`entry.get("link")`, `entry.get("summary")`/`entry.get("title")`, and `published_parsed` (via
`feed_parsing.py::parse_entry_date`). **`media_content`, `media_thumbnail`, `enclosures`, and any
HTML `<img>` inside `summary` are never read.** This is genuinely "available in-process, discarded
by the adapter" — distinct from Telegram/NEWS_API, where the field mostly never existed upstream
at all.

`services/cleaning.py::clean_item()` does **not** strip HTML from the body text (only from the
*title*, via `_clean_title_text`, `cleaning.py:119-130`) — `normalized_text` is whitespace-collapsed
only. This means raw HTML, including `<img>` tags, survives into `NewsEvent.content` for RSS today,
confirmed live in §7.

No code distinguishes a feed-level logo from an article-level image (moot, since neither is
captured), and no `srcset`/`data-src`/lazy-load handling exists (moot, since no HTML image
extraction happens at all yet).

## 6. NEWS_API findings

`SourceType.NEWS_API` (`database/models/news_source.py`) is populated by three adapters, per
`services/adapter_keys.py:45-54`: `github_api` → `GitHubSourceAdapter`, `hacker_news` →
`HackerNewsSourceAdapter`, `arxiv` → `ArxivSourceAdapter`. There is no commercial "News API"
(e.g. newsapi.org-style `urlToImage`) integration anywhere in this repository.

- **GitHub** (`integrations/sources/github_source.py`): fetches `/repos/{owner}/{repo}/releases`.
  `_to_raw_item()` (`:197-218`) builds `text` from the release's raw markdown `body` and takes
  `url=release.get("html_url")`. No image field is read from the JSON response. A release's
  markdown `body` may contain `![](...)` screenshot syntax, which survives as literal text in
  `RawNewsItem.text` but is never parsed into a distinct image URL.
- **Hacker News** (`integrations/sources/hacker_news_source.py`): consumes the public Firebase
  item API, which has no image field at all for typical entries (mostly link posts to `item.url`
  or Ask/Show HN text). `_to_raw_item()` (`:72-94`) never references anything image-related because
  nothing exists to reference.
- **arXiv** (`integrations/sources/arxiv_source.py`): Atom feed via the same `feedparser` path as
  RSS, but `_to_raw_item()` (`:54-70`) only extracts `summary`/`title` and the abstract-page link —
  arXiv's Atom entries have no meaningful "article image" concept for a scientific abstract page,
  and none is fetched.

Live proxy signal (§7): NEWS_API `content` rows contain a literal `<img` substring in only 0.1%
(2 of 1,593) of rows, consistent with GitHub/HN/arXiv text being predominantly plain markdown/text
rather than raw article HTML.

## 7. Article-page / Open Graph metadata findings

**No code anywhere fetches an arbitrary article webpage.** Every `httpx`/`aiohttp`/`requests` call
site in the repository targets a *feed or API endpoint* (RSS/Atom XML, HN Firebase JSON, GitHub
Releases JSON, arXiv Atom XML) — never `NewsEvent.url` or `RawNewsItem.url` as an HTML page to
scrape. Confirmed independently by direct grep and by a dedicated fork covering the same ground.

- `httpx>=0.27` is the only HTTP client in `pyproject.toml`; every adapter builds its own
  `httpx.AsyncClient(timeout=...)` locally — no shared client, no shared retry policy, no shared
  SSRF-safe wrapper exists anywhere in the codebase.
- No HTML-parsing library is a dependency: no `beautifulsoup4`, `lxml`, `selectolax`,
  `readability-lxml`, or `trafilatura`.
- Grep for `og:image|twitter:image|json-?ld|opengraph|BeautifulSoup` across the entire repository
  matches exactly one file, and it is a prior-phase discovery *document*
  (`docs/phase15_editorial_intelligence_discovery_report.md`), not code. **No OG/JSON-LD
  extraction code exists.**
- Grep for `ipaddress`/`ip_address(`/private-IP-blocking patterns returns **zero matches**. No
  SSRF protection of any kind exists anywhere in this codebase today.

**Bounded live network sample** (Step 5 constraint: max 10 pages, 1 request/page, short timeout, no
image bytes, metadata inspection only). 10 distinct real article domains were drawn from live
`news_events` rows (RSS/NEWS_API sources):

| Domain | Result |
|---|---|
| 3dnews.ru | `ConnectTimeout` (TLS handshake) |
| 9to5google.com | `ConnectTimeout` |
| 9to5mac.com | `ConnectTimeout` |
| 9to5toys.com | `ConnectTimeout` |
| abcnews.com | `ConnectTimeout` |
| abhi.now | `ConnectTimeout` |
| academic.oup.com | `ConnectTimeout` |
| addisoncrump.info | `ConnectTimeout` |
| alexklos.ca | **200 OK** — `og:image` present, `twitter:image` present |
| alexwlchan.net | `ConnectTimeout` |

**Finding, clearly caveated:** this execution sandbox has restricted/unreliable outbound network
access to arbitrary internet domains — 9 of 10 well-known, normally-reachable domains timed out at
the TLS handshake stage, which is an environment artifact, not evidence those sites lack OG tags.
The one successful fetch did carry both `og:image` and `twitter:image` meta tags, consistent with
general web-wide OG-tag prevalence on modern published content, but **a single data point is not
statistically meaningful**. This sample must be re-run from the actual production/worker host
(which already makes outbound HTTP calls today, e.g. to `api.github.com`, RSS feed hosts, and the
OpenAI API, so production egress is evidently not this restricted) before any M1 design decision
relies on a specific OG-tag hit-rate estimate.

**Priority order hypothesis (from the task brief), evaluated:** Telegram-native → RSS/NEWS_API
field → OG → JSON-LD → hero-image heuristic → external search. This repository has **zero
evidence against** this ordering (nothing currently contradicts it) but also does not yet have
live evidence strongly *for* the OG/JSON-LD hit-rate at each step, given the sampling limitation
above. The ordering is retained as the working hypothesis for M1, with the explicit caveat that
the OG hit-rate assumption needs re-validation from an unrestricted host.

## 8. Live data availability audit

Read-only PostgreSQL audit against `ai_newsroom_postgres` (no rows modified). Access via
`docker exec ai_newsroom_postgres psql -U postgres -d ai_newsroom`, credentials never printed.

**Schema (verified via `\dt`/`\d`):** 8 tables — `news_events`, `sources`, `editorial_tasks`,
`content_drafts`, `channels`, `users`, `ai_executions`, `alembic_version`. **No `raw_news_items`
table exists** — `news_events` is the earliest persisted stage; there is no raw-payload table to
recover discarded upstream fields from for historical rows. `news_events` has **zero image/media
columns**.

**Volume:** 8,088 total `news_events`.

| Source type | Count | % |
|---|---|---|
| RSS | 5,855 | 72.4% |
| NEWS_API | 1,593 | 19.7% |
| TELEGRAM | 640 | 7.9% |

Categories: UNKNOWN 6,069 (75.0%, largely pre-categorization backlog per Phase 15), AI 1,014,
GADGETS 347, STARTUPS 269, SOFTWARE 227, HARDWARE 80, TECH 74, CYBERSECURITY 8. Distinct sources:
71 RSS domains, 10 NEWS_API sources, 4 Telegram channels.

**Schema-gap finding:** since `news_events` has no image column, "events with a native media
reference" is **not obtainable from stored structured data** — a schema gap, not a data gap. As a
proxy, `content` was scanned for image-URL/tag signatures:

| Source | n | `content` contains `<img` | % |
|---|---|---|---|
| RSS | 5,855 | 1,295 | 22.1% |
| NEWS_API | 1,593 | 2 | 0.1% |
| TELEGRAM | 640 | 0 | 0% |

This is very likely an **undercount** for RSS: the regex only matches literal `<img`, not
`<figure>`/`<picture>`/`srcset`-only markup some feeds use instead.

150-row recent sample (109 RSS / 36 NEWS_API / 5 TELEGRAM): 0 malformed image-like `url` values
(`url ~* '\.(jpg|jpeg|png|webp|gif)'` = 0 — the article `url` field is never itself an image
link), 0 NULL `url`, 0 duplicate `url`. Domain diversity in-sample: 18 RSS domains, 9 NEWS_API
domains, 1 Telegram domain (`t.me`, expected).

**Distinguishing "not provided" vs "discarded" vs "unknown" vs "webpage-fetch-only,"** per source:

| Source | Classification |
|---|---|
| Telegram | **Discarded** (Telethon `Message.photo`/`.document` exist on the object, never read) |
| RSS | **Discarded, recoverable** (`media_content`/`media_thumbnail`/`enclosures`/inline `<img>` all present in `feedparser`'s output, never read) |
| GitHub (NEWS_API) | **Mostly not provided** as a distinct field (release JSON has no image field); markdown-embedded images in `body` are a minor, unparsed exception |
| Hacker News (NEWS_API) | **Not provided** — the upstream API has no image field for typical items |
| arXiv (NEWS_API) | **Not provided** — no meaningful per-article image concept in the Atom feed consumed |
| Any source's original article page | **Available only through webpage fetch** — nothing in this schema stores or has ever fetched article HTML beyond RSS's own partial content dump |

No production rows were modified. No external API/LLM calls were made. No Telegram messages were
sent during this audit.

## 9. Storage findings

**No object/file storage capability of any kind exists.** `docker-compose.yml` (full file
reviewed) defines exactly two named volumes: `postgres_data:/var/lib/postgresql/data` and
`redis_data:/data`. The `backend` service bind-mounts only source directories (`./app`, `./core`,
`./database`) for dev reload — no media volume. No MinIO/S3-compatible service is defined.

- `.env.example` has zero `S3_*`/`MINIO_*`/`AWS_*`/`STORAGE_*`/`BUCKET_*` variables.
- `pyproject.toml` has no `boto3`, `minio`, `Pillow`, `imagehash`, or `python-magic`.
- None of the 8 `database/models/*.py` files has a file-path, content-hash-of-binary, or
  file-metadata column. `NewsEvent.hash` (`news_event.py:58`) is a dedup hash of the *textual*
  event (`source_id + external_id`), unrelated to image bytes.
- No cleanup/retention worker exists anywhere in `worker/` (grepped for
  `retention|cleanup|purge|delete.*older|TTL` — zero matches).
- **Precedent that does exist:** `EditorialTask.workflow` and `ContentDraft.hashtags` are both JSON
  columns already in production use — establishing a JSON-blob storage precedent in this schema,
  but no precedent at all for storing binary file content or file-system paths.

**Recommendation for Phase 16 (not implemented in M0):** store **both** a remote reference and,
only for candidates that survive quality gating and reach the editor, an internal stored copy —
option (C) in the task brief's framing, narrowed by scope. Rationale: remote URLs alone are
unreliable long-term (Telegram CDN URLs expire, source articles get edited/deleted, hotlinking is
sometimes blocked), but downloading every *discovered* candidate (before quality/dedup filtering)
would be pure waste. Concretely: persist lightweight metadata (URL, dimensions, hash, scores) for
all discovered candidates; download and store bytes only for the (≤5) finalists shown to the
editor, or — cheaper still — only for the one ultimately selected. This mirrors the cost-shaping
principle already used elsewhere in this codebase (e.g. `content_generation_scan_limit` vs
`content_generation_batch_size`): scan wide, act narrow.

## 10. Security threat model

Image retrieval is a new untrusted-network boundary with **zero existing protection** (§7). Since
every adapter today builds its own bare `httpx.AsyncClient`, Phase 16 needs one new, shared,
SSRF-safe fetch module — not a copy-pasted safety check per call site.

| Threat | Deterministic protection |
|---|---|
| SSRF to localhost/private/reserved IPs (incl. `169.254.169.254` cloud metadata) | Resolve DNS explicitly, validate every resolved IP with Python's `ipaddress` module (block loopback, RFC1918, link-local, unique-local, multicast) **before** connecting; pin the validated IP for the actual connection (do not re-resolve) |
| DNS rebinding | Same pinned-IP-after-validation approach — validate the IP actually connected to, not just the hostname pre-check |
| Redirect chains to a private IP | Disable automatic redirect-following; manually follow up to a small bounded number of hops (e.g. 3), re-running full scheme+IP validation on every hop |
| Non-HTTP schemes (`file://`, `data:`, `ftp://`) | Explicit `http`/`https`-only allowlist before any connection attempt |
| Credential leakage through redirects | Never send an `Authorization`/cookie header on any external image fetch |
| Oversized downloads | Enforce a `Content-Length` cap where present, **and** a hard streaming byte-counter cutoff regardless of header (a lying/absent header must not bypass the limit) |
| Decompression bombs / extreme pixel dimensions | Check header-declared image dimensions before full decode; cap total decoded pixel count (e.g. via Pillow with an explicit pixel ceiling) before calling `.load()` |
| Malformed images | Decode failure → hard reject, classified error, never a crash that takes down a worker cycle |
| MIME spoofing | Sniff actual content (magic bytes / decoder-confirmed format), compare against the declared `Content-Type`; mismatch → reject |
| Unsafe SVG (scripts, external entity references) | Exclude SVG from the supported-format allowlist entirely for M1–M4; revisit only with a dedicated sanitizer if ever needed |
| Animated-image resource use | Either reject animated formats or explicitly decode only the first frame; flag as animated in metadata either way |
| Tracking pixels | Dimension-based hard reject (§13) |
| Malicious/path-traversal filenames | Never derive a stored filename from any source-provided string; generate from the content hash only |
| Duplicate-download amplification | Dedup by canonicalized URL *before* fetching, not just after (§14) |
| Slow responses / infinite streams | Strict connect and read timeouts; a total per-fetch time budget |
| Excessive concurrency | Bounded global semaphore across all in-flight image fetches |
| Poisoned cache | No shared response cache in M1–M4; if one is added later, key it by content hash, never by URL alone |
| Source-domain impersonation | Not solvable by a fetch-layer control — addressed at the provenance/rights layer (§17) instead, not claimed as a security guarantee here |

TLS verification is never disabled, per the M0 constraint — no exception is proposed anywhere in
this design.

## 11. Candidate data-contract options

| Option | Migration required? | Verdict |
|---|---|---|
| A. Embed in `NewsEvent` metadata | Yes — `NewsEvent` has no JSON column today (only `Enum`/`Text`/`Integer`/`DateTime`, `news_event.py:36-75`); adding one is itself a migration | Rejected for M0 (out of scope); viable for a later milestone, not preferred (see D) |
| B. Persist in `EditorialTask.workflow` `step_results` JSON | No — column already exists (`editorial_task.py:44`) | **Recommended interim carrier for M1–M4** (see below) |
| C. Link to `ContentDraft` | Effectively yes — `ContentDraft`'s only JSON column (`hashtags`) is semantically scoped to hashtags; a real slot needs a new column | Rejected: also couples candidates to drafts that may not exist for events rejected before generation |
| D. Dedicated `ImageCandidate` table | Yes | **Recommended permanent home, from M5 onward** |

**Recommendation:** ship no migration in M0 (as required). For M1–M4 (discovery, secure fetch,
quality gating, ranking), store discovered candidates inside the *existing*
`EditorialTask.workflow.step_results` JSON — exactly the same zero-migration seam
`services/editorial_scoring.py` and `services/fact_safety.py` already use to record their own
deterministic findings onto the `scoring`/`quality` steps (`capabilities/executor.py:190-207`).
This repository has an established, twice-proven pattern: **ship a deterministic capability first
inside the cheapest observable slot (`step_results`), validate it live in shadow mode, then
promote to a real table once evidence justifies the schema commitment** — Editorial Scoring V2 and
Fact Safety both followed exactly this path. Image Intelligence should follow it a third time.
`step_results` is task-scoped (not stable per-`NewsEvent` identity across retries), which is
precisely why it is *not* the final answer — cross-event/global perceptual-hash dedup queries
(§14) and a retention/cleanup job (§9) both need real, indexed rows, which only a dedicated table
in M5 provides.

**Proposed `ImageCandidate` field set** (target shape for the M5 table; equivalent dict shape for
the interim `step_results` JSON entry):

- **Identity**: `id`, `event_id` (FK), `content_draft_id` (nullable FK)
- **Origin**: `image_url`, `source_page_url`, `source_type`, `source_name`, `discovery_method`,
  `telegram_message_id`/`telegram_grouped_id` (nullable — Telethon identifiers, not Bot API
  `file_id`/`file_unique_id`, per §4)
- **Technical metadata**: `mime_type`, `byte_size`, `width`, `height`, `aspect_ratio`, `format`,
  `is_animated`, `content_hash`, `perceptual_hash`
- **Editorial metadata**: `status`, `rejection_reasons` (list), `quality_score`, `relevance_score`,
  `final_rank`, `selected`, `provenance_state` (§17), `rights_review_required`
- **Lifecycle**: `discovered_at`, `validated_at`, `downloaded_at`, `failure_state`,
  `retention_state`

## 12. Quality-gate design

**Hard rejections** (deterministic, cheapest-first ordering): unsupported URL scheme →
fetch/timeout failure → declared-vs-sniffed MIME mismatch → decode failure → below minimum
dimensions → extreme aspect ratio → exact duplicate (content hash) → known placeholder pattern →
unsafe SVG → over byte-size cap → over decoded-pixel cap.

**Soft signals** (feed a bounded score, §15): resolution/area, aspect-ratio suitability
(landscape preferred for a Telegram card), source-priority tier, presence of explicit
width/height metadata, article-origin confidence, likely-logo/banner downgrade (§13).

**Initial threshold candidates — explicitly flagged as needing calibration, not tuned values:**

| Gate | Initial guess | Calibrate against |
|---|---|---|
| Min dimensions | 400×300 px | M3 live rejection-rate review — too many false rejects means raise the bar less aggressively |
| Aspect ratio bounds | 0.4–2.5 | Same |
| Max file size | 8 MB | Threat-model byte cap (§10), not editorial judgment |
| Max decoded pixels | ~40 MP | Decompression-bomb defense (§10), generous enough for legitimate photos |

Telegram presentation constraint to account for: images are shown inside a card capped by
Telegram's own message/photo rendering — extreme aspect ratios degrade badly there, so the
aspect-ratio soft signal should weight moderately, not just gate hard.

## 13. Logo/avatar/banner/ad detection

| Signal | Hard-reject | Downgrade | Manual-review |
|---|---|---|---|
| Tiny fixed dimensions (e.g. ≤64×64, favicon-shaped) | ✓ | | |
| Filename/path contains `logo`/`icon`/`favicon`/`avatar`/`sprite` | | ✓ | |
| Extreme aspect ratio typical of banners (e.g. >4:1) | | ✓ | |
| Same exact image (content hash) reused across many unrelated events/sources | | ✓ (repeated-use penalty scales with distinct-event count) | |
| Alt text matching known placeholder/ad vocabulary | | ✓ | |
| Ambiguous — small-but-not-trivial dimensions, no strong signal either way | | | ✓ |

Deterministic rules **cannot** reliably distinguish an editorial photo from a well-disguised ad
banner with certainty — this is stated explicitly as a limitation, not solved. The manual-review
bucket exists precisely because some cases are genuinely ambiguous without semantic understanding
(deferred to M8, §21).

## 14. Deduplication design

Layered, cheapest-first: (1) canonicalized URL (strip tracking query params, normalize scheme/host
case) → (2) Telethon message/media identifier where applicable (the closest analog to Bot API
`file_unique_id` in this codebase's actual collection path, per §4) → (3) exact content hash
(sha256 of bytes, mirroring `NewsEvent.hash`'s own precedent) → (4) perceptual hash (requires a new
dependency, e.g. `imagehash`; only computed after bytes are already downloaded for another reason,
never used to justify a download by itself) → (5) dimension/crop similarity heuristics, lowest
priority and only where (1)–(4) leave ambiguity.

Perceptual-hash Hamming-distance threshold: no calibration data exists yet — start conservative
(e.g. ~8–10 for a 64-bit phash) and tighten/loosen only after M3 live review shows false
merges/misses. Scope: dedup **within one event** is the M1–M4 priority (directly serves the
"up to 5 distinct candidates" requirement); cross-event dedup (the same syndicated photo appearing
under multiple `NewsEvent` rows) is a secondary, lower-priority scope for later milestones, since it
requires the M5 dedicated table's indexed hash lookups to be efficient at all. Global/per-source
dedup is explicitly out of scope until real volume data justifies it. Visually similar but
editorially distinct images (e.g. two different photos from the same press event) are never merged
— only hash-based or near-identical-crop matches qualify as "duplicate."

## 15. Deterministic relevance ranking

Zero-LLM, 0–100 bounded score with a transparent component breakdown, matching this repository's
own established pattern (`editorial_scoring_weight_*` settings fields, weights sum to 1.0, tested
against exact defaults rather than cross-field-validated — `core/config.py:171-175` and its
accompanying test, the same "tested-not-validated" convention this Settings class already uses
elsewhere).

| Component | What it measures | Missing-data behavior |
|---|---|---|
| Provenance/source priority | Native Telegram post > article-embedded > RSS/API field > OG/JSON-LD > third-party search (deferred) | Neutral/minimum value, never a bonus, if discovery method is unknown |
| Technical quality | Resolution, aspect-ratio suitability | Neutral if dimensions couldn't be determined (should be rare post-decode) |
| Textual relevance | Token overlap between `NewsEvent.title`/content and image alt-text/filename/surrounding context, where available | Neutral (not zero, not full credit) when no textual signal exists — most images will have none, and that must not systematically penalize every Telegram-native photo, which has no alt text by construction |
| Duplicate penalty | Reduces score for near-duplicate/lower-resolution copies of another candidate in the same event | N/A if no duplicate found |
| Logo/banner penalty | From §13's downgrade signals | N/A if no signal fires |
| Discovery-method reliability | Static weight per method | N/A |
| Freshness | Only meaningful if discovery timestamp varies meaningfully within one event's short candidate-gathering window; likely near-constant in practice | Neutral |

Explicit rules: no source type gets an artificial advantage merely because it has less metadata to
evaluate (the "neutral, not bonus" rule above enforces this); ties break deterministically by
candidate identity (e.g. UUID or stable discovery order), never by random choice; no claim about
image *content* semantics is ever made beyond what's in available metadata — this is a metadata/
provenance ranking, not a vision model, and is not presented as one.

## 16. Rights and provenance policy

This is a technical policy, not legal advice. For every candidate, the system preserves: exact
originating page, exact image URL or Telegram origin, discovery method, source attribution, date
found, and an explicit `provenance_state`:

- `original_source_media` — came from the Telegram post or the source's own article page directly
- `source_page_media` — extracted via OG/JSON-LD from the article page, still first-party
- `third_party_unknown` — origin outside the original post/article (deferred entirely until a
  search-based discovery layer exists, which is not part of M1–M7)
- `rights_review_required` — ambiguous or the automated pipeline cannot establish which of the
  above applies

Recommended initial editorial preference order: media included in the original Telegram post >
media embedded in the original article > official press assets with explicit provenance. External
search-engine results are never automatically treated as reusable — nothing in this design
"proves" reuse rights; it only proves *where an image was technically found*, which is what the
system can honestly assert.

## 17. Telegram UX recommendation

Current state (verified, §4): the editorial bot renders one plain-HTML text card per draft via
`render_editorial_card()`/`bot.send_message()`. `bot/keyboards/` is an empty reserved package —
**no inline-keyboard or callback-query infrastructure exists today.** This is a green-field
addition, not an extension of existing UI code.

**MVP recommendation:** keep the existing text card completely unchanged (zero risk to the
already-tuned 4096-character truncation logic), then — only if ≥1 valid candidate exists — send one
follow-up message: the top-ranked image via `send_photo`, short caption, with an inline keyboard
(Prev / Next / Reject / Use no image / Open source). This is closest to option (C) in the task
brief's framing (separate candidate message linked to one draft), chosen over embedding the image
as the *first* message's photo+caption because Telegram's photo-caption limit (1024 characters) is
far tighter than the already-carefully-managed 4096-character text card, and reusing that budget
would risk destabilizing existing, tested logic for a Phase 16 M0 deliverable that must not touch
production code.

Concrete new pieces this requires (not built in M0): a callback-query router in `bot/handlers/`,
`callback_data` encoding bounded to a small candidate index (≤5, well under Telegram's 64-byte
`callback_data` limit), and idempotent handling of a repeated/duplicate callback (a user tapping
twice). Required editor actions per the task brief — choose, next/previous, reject, use-no-image,
open-source, inspect-provenance — all map cleanly onto this shape.

## 18. Performance / cost estimate

Runtime state confirms `content_generation_batch_size=5`, `news_analysis_batch_size=5`, and
automation currently disabled at the account level per the task brief's expected state
(collection/analysis/generation enablement flags are a live-config question, not re-verified
bit-for-bit here since it doesn't change the M0 design). Roughly ~1,000 raw events/day are
collected, but only the much smaller subset that reaches a *drafted* `ContentDraft` should ever
trigger image work — bounding cost by construction, not by a new rate limiter.

Proposed limits (all configurable, none hardcoded as architecture):

| Limit | Proposed value | Rationale |
|---|---|---|
| Max candidates *discovered* per event | 8 | Headroom above the 5 final slots for post-filter attrition |
| Max images *downloaded* per event | 5 | Matches the "up to five" editorial requirement directly |
| Max bytes per image | 8 MB | Threat-model cap (§10) |
| Max total bytes per event | 40 MB | 5 × 8 MB ceiling |
| Max concurrent downloads (global) | 5 | Bounded worker resource use |
| Per-domain concurrent requests | 2 | Politeness / avoids hammering one source |

No infrastructure dollar pricing is fabricated here — none of this repository's config or docs
establishes a hosting-cost baseline to extrapolate from, and inventing one would violate the "don't
fabricate exact infrastructure prices" instruction. The qualitative claim that can be made
confidently: cost scales with *drafted* events, not *collected* events, which is the single most
important cost lever available.

## 19. Failure behavior

Text-only `ContentDraft` delivery must never be blocked by Image Intelligence, at any stage: no
candidates found, all candidates rejected, source page unavailable, storage unavailable, hash
failure, timeout, or unsupported format all resolve to "proceed without an image," never a hard
failure of the surrounding workflow step.

**Rollout flag naming, evaluated against this repo's own convention:** the task brief proposed
`IMAGE_INTELLIGENCE_MODE=off|shadow|editorial`. This repository has an established **three-state
`off|shadow|enforce`** convention used identically by `fact_safety_mode` and `llm_budget_mode`
(`core/config.py:58`, `:190`) — "editorial" is not the term this codebase uses for "the mode where
behavior actually changes." Recommendation: **prefer `off|shadow|enforce` for consistency**, even
though "enforce" reads slightly oddly for a feature that surfaces choices rather than blocking
anything — `fact_safety_mode`'s own `enforce` state is the nearest precedent (it withholds
delivery based on shadow findings, which is a *behavior change*, exactly what Image Intelligence's
"editorial" state would also be). This is flagged as an open naming call for whoever owns M6, not
decided unilaterally here.

## 20. Recommended architecture

1. **Capability name:** not a `Capability` (that framework — `capabilities/registry.py:60-67` — is
   explicitly LLM-provider-facing: every registered capability is constructed with
   `(gateway, prompt_repository)` and the `Capability` protocol's own docstring says "Never calls a
   provider SDK" in a way that only makes sense if calling one *would* otherwise be the norm).
   Instead: a new deterministic **service**, `services/image_intelligence.py`, following the exact
   pattern of `services/fact_safety.py` and `services/editorial_scoring.py`.
2. **Place in workflow:** hooked inside `capabilities/executor.py::CapabilityExecutor` via
   `if step.capability == "copywriting":`, the same mechanism already used for
   `if step.capability == "scoring":` (editorial scoring v2) and `if step.capability == "quality":`
   (fact safety) at `capabilities/executor.py:190-207`. Chosen over a brand-new
   `WorkflowStepDefinition` because it needs zero change to `workflows/registry.py`,
   `workflows/runner.py`, or `schemas/workflow.py` — identical "zero-change to the Workflow Engine"
   property Fact Safety's own contract explicitly required.
3. **Before or after CONTENT_GENERATION:** *inside* it, after the `copywriting` step, because
   textual relevance ranking (§15) needs the drafted title/body text, which does not exist before
   that step runs.
4. **Tied to NewsEvent or ContentDraft:** both — discovery keys off `NewsEvent` (image sources are
   properties of the event, not the draft), but ranking/selection happens in the context of one
   `ContentDraft`'s text.
5. **Runs for all events or only drafts:** only for events that reach a successful `copywriting`
   step — i.e., only drafted events, not all ~1,000 daily collected events (§18).
6. **New worker required:** no. `worker/content_cycle.py` already owns the `CONTENT_GENERATION`
   run loop; the new service call happens inside the existing `CapabilityExecutor` invocation it
   already makes.
7. **Existing worker owns the MVP:** yes — `content_worker` (already running,
   `ai_newsroom_content_worker` in `docker-compose.yml`).
8. **Migration required:** no, for M1–M4 (uses `EditorialTask.workflow.step_results`, §11). Yes,
   for M5 (`ImageCandidate` table).
9. **Storage strategy:** metadata-only during discovery/ranking; bytes stored only for the ≤5
   editor-facing finalists (§9).
10. **Download-security boundary:** one new shared fetch module (not per-adapter), implementing
    §10 in full — this is the single most important new component in Phase 16.
11. **Deduplication boundary:** within-event first (§14); cross-event/global deferred to when the
    M5 table makes indexed lookups practical.
12. **Telegram presentation boundary:** a new follow-up message + inline keyboard, existing text
    card untouched (§17).
13. **Rollback:** `IMAGE_INTELLIGENCE_MODE=off` (or whatever final name, §19) reverts to exactly
    today's byte-identical text-only behavior — no code path removal needed, matching this
    repository's own `fact_safety_mode`/`editorial_scoring_version` rollback precedent.
14. **Cost guard:** bounded by construction (§18) — drafted-events-only scope, per-event candidate/
    byte caps, bounded concurrency. No LLM/paid-API calls anywhere in M1–M7.
15. **Observability:** structured log events per candidate (discovered/validated/rejected/selected)
    mirroring this repo's existing `logger.info("...", extra={...})` convention throughout
    `services/`, plus the `step_results` JSON itself serving as an inspectable audit trail during
    shadow mode, exactly as Fact Safety's shadow mode already does.

Preserves the modular architecture throughout: no image-fetching logic is placed inside
`bot/handlers/`, `workflows/runner.py`, or `capabilities/executor.py`'s own body beyond the single
existing `if step.capability == ...` hook pattern already used twice. No microservice is justified
— this repository has no precedent for one, and nothing about Image Intelligence's scope demands
independent deployment/scaling from `content_worker`.

## 21. Migration recommendation

**None in M0 or M1–M4.** A migration is recommended starting at **M5** (Persistence and
retention), to add a dedicated `image_candidates` table — needed for indexed content-hash/
perceptual-hash lookups (cross-event dedup, §14), a retention/cleanup job (§9), and stable
candidate identity independent of any one `EditorialTask` run. This exactly mirrors how both
Editorial Scoring V2 and Fact Safety shipped their first, validated version with **zero** schema
change before any migration was considered.

## 22. Risks and limitations

- The bounded network sample (§7) is not statistically meaningful (1/10 domains reachable from
  this sandbox) — the OG-tag hit-rate assumption needs re-validation from the real worker host
  before M1 designs around a specific percentage.
- The RSS `<img>`-in-content proxy signal (22.1%) is very likely an undercount, since it only
  matches literal `<img` and misses `<figure>`/`<picture>`/`srcset`-only markup.
- Deterministic logo/ad/banner detection (§13) has known false-negative risk — stated explicitly,
  not glossed over.
- Perceptual-hash thresholds (§14) and quality-gate dimension/aspect-ratio thresholds (§12) are
  reasoned starting points, not calibrated against real Phase 16 data (none exists yet).
- Telethon-based media download (`message.download_media()`) was identified as feasible by API
  shape but was **not exercised** in M0 — no message media was downloaded, per the "no image-body
  downloads" constraint; this remains to be proven working in M1/M2, not just plausible.
- `EditorialTask.workflow.step_results` as the M1–M4 carrier is task-scoped, not event-scoped —
  re-running `CONTENT_GENERATION` for the same event (e.g. after a retry) would not automatically
  see a prior run's discovered candidates without additional logic; this is an accepted, documented
  limitation of the interim (pre-M5) storage choice, not a defect.

## 23. M0 verdict

All required discovery, live-data auditing, security threat-modeling, and architecture-decision
work is complete, evidence-backed, and does not require an irreversible action, a migration, paid
API access, or public disclosure to proceed. See the companion
`docs/phase16_image_intelligence_implementation_plan.md` for the milestone-by-milestone
implementation plan this report feeds into.

**PHASE 16 M0 COMPLETE — IMAGE INTELLIGENCE READY FOR IMPLEMENTATION**
