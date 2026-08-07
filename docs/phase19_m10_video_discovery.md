# Phase 19 M10 — Media + Source-Local Video Discovery

## 1. Scope — bounded, source-local only

The overnight authorization's own closed allow-list, enforced exactly:

- RSS enclosure `video/*`
- RSS `media_content[medium=video]`
- HTML `<video>`/`<source>`
- `og:video` / `og:video:url` / `og:video:secure_url`
- Twitter Player Card (`twitter:player:stream`)
- YouTube/Vimeo/explicit-official-video links **already present** in the selected article's HTML

**Explicitly not implemented, by design**: no open web search, no video search engine, no
YouTube/Vimeo API call, no transcoding, no ffmpeg dependency. YouTube/Vimeo candidates are
classified by URL pattern only (`services/video_discovery.py::classify_video_url()`) and never
fetched.

## 2. Extraction (`services/video_discovery.py`)

- `extract_rss_native_video(entry)` — mirrors `services/image_intelligence.py::
  extract_rss_native_media()`'s exact shape, filtering `media_content`/`enclosures` FOR video
  (`medium="video"` or a `video/*` MIME type) instead of image.
- `extract_article_video_metadata(html, base_url)` — mirrors `services/article_metadata.py`'s
  stdlib-`HTMLParser`-only convention exactly (no BeautifulSoup/lxml). Priority order:
  `og:video:secure_url` > `og:video`/`og:video:url` > `<video>`/`<source>` > Twitter Player Card >
  YouTube/Vimeo links already in the HTML.

## 3. Direct-hosted validation (never for YouTube/Vimeo)

`validate_direct_hosted_video()` — bounded `safe_fetch()` (new `video_discovery_*` settings block,
mirrors `article_acquisition_*`'s exact convention) + stdlib magic-byte sniffing only:
`ftyp` box at byte offset 4 (MP4/MOV/M4V family) or an EBML header at offset 0 (WebM/MKV). Never a
real decode, never ffmpeg. YouTube/Vimeo candidates skip this entirely
(`VideoValidationStatus.UNVALIDATED_HOSTED_PLATFORM`) — validated by URL pattern only.

## 4. Wiring — zero additional network request for extraction

`services/article_acquisition.py::acquire_article()` (Phase 19 M1) already fetches and decodes
the article's raw HTML for text extraction. M10 reuses that exact same in-memory HTML — extraction
costs nothing extra. `AcquisitionOutcome` gained one new, additive, defaulted field
(`discovered_video_hints: list = field(default_factory=list)`) so every pre-existing call site is
unaffected. `get_or_acquire()` persists these hints (best-effort, SAVEPOINT-guarded, a persistence
failure never affects the article-acquisition row it wrote just before) whenever
`video_discovery_mode != "off"` — direct-hosted candidates get one bounded validation fetch each;
YouTube/Vimeo candidates get none.

This creates one disclosed dependency: video discovery from article HTML can only run when article
acquisition itself runs (i.e. in practice also needs `article_acquisition_mode != "off"`) — the
same shape as M7/M8's own "requires story_memory_mode != off too" dependency.

## 5. Persistence

New standalone table `content_draft_media_items` (1:many, surrogate PK + FK to `content_drafts.id`
and `news_events.id`, both indexed) — migration `f2654fa00185`, chained onto M9's implicit head
(M8's `8faedf40f596`), written but not applied live. `media_type` is a plain string, scoped to
`"video"` for this milestone; named generically because this table is the shared future home for
M11's media ranking (existing image candidates stay in the unmodified `image_candidates` table —
unifying that data into this new table is explicitly out of M10's own narrow scope, per "don't
rewrite an existing system when an extension point already exists").

`services/video_discovery_persistence.py` is the sole constructor of `ContentDraftMediaItem` rows
— same capabilities-never-import-database-models indirection as every other Phase 19
shadow-persistence module.

## 6. Setting

```python
video_discovery_mode: Literal["off", "shadow", "enforce"] = "off"
```

"off" (default): zero processing. "shadow": hints extracted and, for direct-hosted candidates,
bounded-validated; persisted for review only. "enforce": at the M10 layer alone, behaves
identically to "shadow" — the distinction only becomes meaningful once M11 (media ranking) and
M12 (Telegram delivery) exist to actually consume these candidates for something beyond review;
until then "enforce" does not yet change any real behavior (mirrors `story_memory_mode`'s own
"enforce not yet implemented" disclosure from Phase 18.10).

## 7. Validation performed

- Disposable Postgres, migrated through `f2654fa00185`, upgrade/downgrade/re-upgrade all clean.
- `tests/test_video_discovery.py` (28 tests): pure extraction/classification, no network.
- `tests/test_video_discovery_validation.py` (4 tests): `validate_direct_hosted_video()` with
  `safe_fetch()` mocked directly — MP4/WebM accepted, non-video bytes rejected, a `SafeFetchError`
  surfaces its structured error code.
- `tests/test_video_discovery_persistence.py` (3 tests): fake-session persistence shape.
- `tests/test_video_discovery_integration.py` (2 tests): real, migrated-database proof that
  `get_or_acquire()` persists discovered hints under `"shadow"` and nothing under `"off"` — runtime
  table-existence skip against the real, unmigrated dev DB.
- Full pre-existing `tests/test_article_acquisition*.py` suites (17 tests, unmodified) still pass.
- Ruff/Mypy clean.

## 8. What this milestone does NOT do

- Does not enable `video_discovery_mode` anywhere (defaults `"off"`).
- Does not perform any open web/video search or call a YouTube/Vimeo API.
- Does not transcode or decode video (no ffmpeg dependency introduced).
- Does not migrate existing image-candidate data into the new table.
- Does not build M11's ranking or M12's Telegram delivery — those are separate milestones.
