# Media Roadmap Recovery Report

Read-only audit. No code changed, no config changed, no schema created, no live canary run.
Findings are backed by direct repository inspection (file/line citations) and phase documentation
(Phase 16 M0–M8, Phase 19 M9–M13), cross-checked against the current, real code in
`worker/content_cycle.py` and the services it actually calls — not assumed from docs alone.

---

## Executive summary

This project ran a genuinely thorough, disciplined media roadmap (Phase 16 M0–M8, Phase 19
M9–M13) that built real discovery, ranking, multi-image, and video capabilities — almost all of
it working, tested, and validated. **Almost none of it is wired into the live NEWS delivery
path.** The single most important finding: `worker/content_cycle.py`'s router branch calls
`get_editorial_image_candidates()` (which *can* return up to 5 real, ranked candidates) and then
**deliberately `break`s after the first successfully-resolved one** — a fact the codebase's own
comments already state explicitly elsewhere (`services/image_persistence.py:409`: *"worker/
content_cycle.py always resolves `image_candidates[0]`"*). Multi-image, media ranking (M11), rich
media delivery via `send_media_group()` (M12), and video discovery (M10) all exist as real, tested
code and are **never called** from the live path at all. This is not a gap in what was built — it
is a gap in what was *turned on*.

---

## 1. Original intended media roadmap

Reconstructed from `docs/phase16_image_intelligence_discovery_report.md` (M0) and the
`docs/phase19_m9_*` through `m13_*` milestone reports, in intended sequence:

**Phase 16 (image foundation):**
- M0: discovery/threat-model/architecture (no code)
- M1: native-source image extraction (Telegram photo/document, RSS media fields)
- M2: secure fetch + article-page metadata discovery (OG/JSON-LD/Twitter-card/`image_src`)
- M3: quality gating + within-event deduplication
- M4: deterministic relevance ranking
- M5: dedicated `image_candidates` persistence table + retention
- M6: Telegram editorial preview (single photo + inline keyboard)
- M7: shadow validation
- M8: local production readiness

**Phase 19 (extensions):**
- M9: deterministic media-quality pre-filter (watermark/lower-third/screenshot heuristics)
- M10: source-local video discovery (RSS/OG/HTML `<video>`/YouTube-Vimeo-by-URL-only)
- M11: deterministic media ranking + cross-event story-aware reuse prevention
- M12: rich media Telegram delivery (`send_media_group`, multi-photo + trailing video)
- M13: optional final-candidate vision review (LLM-based quality/relevance check)

The roadmap's own explicit non-goals throughout: no third-party/search-based image discovery, no
video transcoding, no cross-story image *borrowing* (only *reuse prevention* — the opposite
concern), no automatic vision-based gating without a human-authorized manual harness.

---

## 2. What is actually implemented now (verified in code, not docs alone)

| Capability | File(s) | Real? |
|---|---|---|
| Telegram-native image extraction | `services/image_intelligence.py` (`TELEGRAM_PHOTO`/`TELEGRAM_DOCUMENT` discovery methods) | Yes |
| RSS-native image extraction | same file (`RSS_MEDIA_CONTENT`/`RSS_ENCLOSURE`/`RSS_MEDIA_THUMBNAIL`/`RSS_INLINE_IMAGE`) | Yes |
| Article-page OG/JSON-LD/Twitter-card discovery | `services/article_metadata.py::extract_article_image_metadata()`, called from `image_intelligence.py::_fetch_article_metadata_hints()` | Yes — 5 real discovery methods (`OPEN_GRAPH_SECURE_IMAGE`/`OPEN_GRAPH_IMAGE`/`JSONLD_ARTICLE_IMAGE`/`TWITTER_IMAGE`/`IMAGE_SRC_LINK`), not merely the M0 hypothesis |
| Secure fetch (SSRF protection, size/pixel caps, MIME sniffing) | `services/image_validation.py` | Yes |
| Deterministic quality gating (hard rejects, logo/banner/watermark/TV-lower-third/screenshot signals) | `services/image_quality.py` | Yes |
| Within-event deduplication | `services/image_deduplication.py` | Yes |
| Relevance ranking (0–100, provenance/quality/textual-overlap/dedup penalties) | `services/image_relevance.py` | Yes — this is the module I re-weighted in Phase 23.1N.1 |
| Persistence (dedicated table, up to 5 ranked finalists) | `services/image_persistence.py`, `database/models/image_candidate_record.py` | Yes, migration applied |
| Cross-event duplicate-image guard | `services/image_persistence.py::get_recently_attached_image_source_urls()` | Yes |
| Single-photo Telegram delivery + inline keyboard (legacy card) | `services/image_preview_notifier.py::send_news_with_image_preview()` | Yes |
| Source-local video discovery (RSS/OG/HTML/YouTube-Vimeo-by-pattern) | `services/video_discovery.py` | Yes |
| Direct-hosted video validation (magic-byte sniffing) | `services/video_discovery.py::validate_direct_hosted_video()` | Yes |
| Video persistence | `services/video_discovery_persistence.py`, `content_draft_media_items` table | Yes, migration written, **not applied to real DB** |
| Deterministic media ranking (images + video together, role assignment) | `services/media_ranking.py` | Yes, pure/no I/O |
| Cross-event story-aware media reuse prevention | `services/media_ranking.py::find_story_reused_image_signatures()`/`find_story_reused_video_urls()` | Yes |
| Multi-photo + trailing-video Telegram delivery (`send_media_group`) | `services/image_preview_notifier.py::send_news_with_rich_media()`/`build_rich_media_plan()` | Yes, fully tested |
| LLM vision review of a final candidate | `capabilities/media_vision_review_capability.py` | Yes, but manual-harness-only, never run against a real provider |

**Everything in this table is real, tested code.** The question is never "does it exist" — it's
"does anything in the live path call it."

---

## 3. What is active in the real NEWS path

Traced directly through `worker/content_cycle.py`'s router branch (the only branch any real
canary has used):

1. `get_editorial_image_candidates(session, content_draft_id=...)` — queries the real
   `image_candidates` table, returns rows with `eligible_for_editorial=True`, ordered by `rank`.
   **Active** (real `.env`: `IMAGE_INTELLIGENCE_MODE=shadow`, `IMAGE_CANDIDATE_PERSISTENCE_MODE=finalists` —
   discovery, ranking, and persistence of up to 5 finalists genuinely run for every drafted
   event).
2. `get_recently_attached_image_source_urls()` — cross-event dedup guard. **Active.**
3. A `for candidate in image_candidates:` loop that skips expired/recently-duplicated candidates
   and **`break`s immediately after the first successfully-resolved one**
   (`worker/content_cycle.py:558-569`). **This is the entire "selection" logic** — no ranking
   comparison happens here at all (the candidates arriving in this loop are already rank-ordered
   by the earlier query; this loop just takes the first survivor).
4. `send_photo_to_editorial_destination()` (single photo, one `InputFile`/`file_id`) or
   `send_to_editorial_destination()` (text-only fallback if no candidate resolved or the caption
   would exceed 1024 UTF-16 units). **Active — single-image only, by construction.**

Everything else from §2 — video discovery, media ranking's role/composite scoring, rich-media
`send_media_group`, vision review — is **never referenced** anywhere in `worker/content_cycle.py`
(confirmed by direct grep: zero matches for `rank_media_candidates`, `send_news_with_rich_media`,
`ContentDraftMediaItem`, or `video`, in that file).

**No UPDATE-specific media handling exists anywhere** (confirmed: zero references to
`is_story_update` in `image_persistence.py`/`image_intelligence.py`/`media_ranking.py`) — an
UPDATE reply and a NEW root post go through byte-identical image selection logic. This is
consistent with the intended design (media selection is a property of the event/draft, not of the
story-update relationship) — not a gap.

---

## 4. What is dormant/disabled

| Component | State | Why dormant |
|---|---|---|
| `services/media_ranking.py` (M11) | Built, tested (20+4 tests), **never called** from any live/canary path | M12's own doc: wiring requires "a specific draft's ranked media candidates to actually be computed and available at delivery time" — deliberately deferred to "a future, separately-reviewed milestone" |
| `services/image_preview_notifier.py::send_news_with_rich_media()` (M12) | Built, tested (10 tests, real `send_media_group()` call proven against a fake session), **never called** from `worker/content_cycle.py` | Same as above — explicitly documented as "additive and risk-free... nothing in the existing delivery path changes" |
| `rich_media_mode` setting | Code default `"off"`, **not set in real `.env`**, **never overridden by any canary script** (confirmed by repo-wide grep) | Never exercised even in shadow, ever, in this project's history |
| `services/video_discovery.py` (M10) | Built, tested (28+4+3+2 tests), persistence wired into `article_acquisition.py::get_or_acquire()` | Gated behind `video_discovery_mode`, code default `"off"`, **not set in real `.env`**, **never overridden by any canary** — so even the *discovery* half has never run against real live traffic, only offline tests |
| `content_draft_media_items` table (M10/M11's shared home) | Migration `f2654fa00185` **written but not applied** to the real dev DB | Never applied per this project's own "ship code, validate offline, apply migrations only when ready" convention — consistent with every other unapplied migration in this repo |
| `capabilities/media_vision_review_capability.py` (M13) | Built, tested, registered in the capability registry | Structurally isolated by design (`tests/test_media_vision_review_isolation.py` mechanically enforces no automatic caller); its manual harness script has **never been executed against a real provider**, ever |
| Phase 16 M9's watermark/TV-lower-third/screenshot soft signals | Built, wired into `image_quality.py`'s existing `analyze_candidate()` | Rides the existing `image_intelligence_mode="shadow"` gate — genuinely active as *scoring input*, but only ever produces a `possible_*` warning/score penalty, never a hard rejection; doesn't change what gets selected in a way that would surface as new user-visible behavior |

---

## 5. What is genuinely missing (no code exists at all)

- **True cross-source/alternative-outlet image borrowing** — i.e., using outlet B's image when
  outlet A (the event actually selected for delivery) has none. Confirmed absent by repo-wide
  search; explicitly out of scope through Phase 19 M13 per the M0 report's own "third-party search
  deferred entirely" provenance policy. `media_ranking.py`'s story-aware logic does the *opposite*
  (prevents accidental reuse), not borrowing.
- **A UI/decision layer for the M6 editorial-preview inline keyboard's richer actions** beyond
  what's already built (choose/next/previous/reject/use-no-image) in a *router-mode* context —
  the M6 preview mechanism exists but router mode (the actual production delivery path) bypasses
  it entirely in favor of the simpler single-photo send.
- **Any mechanism to compare/select between an image and a video for the same story** beyond what
  `media_ranking.py`'s role assignment already computes on paper (`HERO` vs `DEMO_VIDEO` vs
  `CONTEXT_VIDEO`) — this logic exists and is tested, but since nothing calls it, there is no live
  image-vs-video selection happening anywhere.
- **YouTube/Vimeo oEmbed or thumbnail extraction** — M10 explicitly classifies these by URL
  pattern only and never fetches metadata from them; a thumbnail-only fallback for a
  YouTube/Vimeo-only story does not exist.

---

## 6. Explaining the three observed behaviors

**"Some stories have no image even though the source page visibly contains one."**
Known from the existing architecture, not a mystery. Concrete, ranked reasons in the actual live
path: (a) `image_intelligence_mode="shadow"` means the whole discovery/ranking pipeline runs and
persists candidates, but nothing in this setting itself *blocks* delivery on a bad/no result —
that's inherent, not a bug; (b) the quality gate can hard-reject every discovered candidate
(logo/banner/tiny/wrong-aspect-ratio/duplicate) — Phase 23.1O's own review confirmed this happens
correctly ("7/16 text-only posts... confirmed correctly 'no candidates existed' in every case");
(c) OG/JSON-LD extraction requires `article_acquisition_mode`-driven article fetch to succeed at
all — a source that fails to fetch (paywall, timeout, bot-blocking) yields zero article-level
candidates even if a human browser would see an image fine; (d) the cross-event duplicate guard
(`get_recently_attached_image_source_urls`) can legitimately skip an otherwise-good candidate if
its exact URL was used on a different recent post. None of this is a bug — it is the documented,
tested, intended behavior of an already-shadow-active pipeline.

**"Delivered stories use only one image."**
Directly explained by §3: the router branch's `break` after the first resolved candidate. Not a
missing feature waiting to be built — the multi-image capability (M11 ranking + M12
`send_media_group`) already exists, fully tested, and is simply never invoked. This is the
clearest case of "dormant wiring" in the entire audit.

**"Video is not appearing in NEWS output."**
Two independent, compounding reasons, both already known from the architecture: (1)
`video_discovery_mode="off"` in the real `.env` (never overridden by any canary, ever) — so video
*discovery* itself has never run against real traffic; (2) even if it had, `worker/content_cycle.py`
has zero video-handling code of any kind — no path exists to deliver a video today regardless of
whether one was discovered, since M12's `send_news_with_rich_media()` (the only function in this
codebase that can send a video) is never called.

---

## 7. Whether video support already exists anywhere

**Yes, substantially — as dormant, tested code, never exercised live.** Discovery
(`video_discovery.py`), validation (magic-byte sniffing for direct-hosted files), persistence
(`content_draft_media_items`, migration unapplied), ranking (`media_ranking.py` assigns
`DEMO_VIDEO`/`CONTEXT_VIDEO` roles), and delivery (`send_news_with_rich_media()`'s
`InputMediaVideo` composition, images-first-video-last ordering, YouTube/Vimeo-as-caption-link
fallback) are all real, tested code. Nothing in this codebase has ever sent a real video to
Telegram — not in a canary, not in a test against a live API (all video tests use fakes/mocks).

---

## 8. Exact reusable components (for whoever scopes the next phase)

- `services/media_ranking.py::rank_media_candidates()` — pure, deterministic, already handles
  images and video together, already has story-aware reuse prevention. Nothing to rebuild.
- `services/image_preview_notifier.py::send_news_with_rich_media()`/`build_rich_media_plan()` —
  already implements the 2–10 item Telegram media-group constraint, caption-on-first-item-only
  rule, images-first/video-last ordering, and single-photo fallback. Nothing to rebuild.
- `services/video_discovery.py` — already implements the full closed-list extraction/validation
  scope authorized in M10. Nothing to rebuild for discovery itself.
- `get_editorial_image_candidates()` already returns a *ranked list*, not a single value — the
  data shape needed for multi-image selection already flows this far; only the consumption loop
  in `content_cycle.py` truncates it to one.
- `services/image_persistence.py::get_recently_attached_image_source_urls()` — the existing
  cross-event dedup guard generalizes cleanly to a multi-image selection loop (same pattern, just
  not `break`ing after one).

## 9. Exact gaps (what would need new code, however small)

- No caller anywhere passes `image_candidates` (plural, ranked) into
  `rank_media_candidates()`/`send_news_with_rich_media()` from `worker/content_cycle.py`'s router
  branch — this is the single load-bearing missing wire.
- `video_discovery_mode`/`rich_media_mode` have never been exercised even in shadow against real
  traffic — turning them on for the first time, even in shadow, is new *operational* ground
  (untested against real data volume/latency), even though the code itself is tested against
  fakes.
- The `content_draft_media_items` migration (`f2654fa00185`) has never been applied to the real
  dev DB — required before video persistence can do anything live.
- No code today decides *when* to prefer a multi-image group over a single photo, or a video over
  an image, using `media_ranking.py`'s own `recommended_role`/`eligible_for_delivery` output at
  the actual delivery decision point in `content_cycle.py` — the ranking function exists, but the
  glue that would call it with real candidates and act on its verdict does not.

---

## 10. Recommended implementation order

Each item labeled per your taxonomy. Ordered narrowest-safest-first, matching this project's own
established "wire before extend, extend before invent" discipline.

1. **WIRING ONLY** — Call `media_ranking.py::rank_media_candidates()` on the already-fetched,
   already-ranked `image_candidates` list inside the router branch's image loop, and use its
   `eligible_for_delivery`/`recommended_role` output instead of the raw `break`-on-first
   heuristic. Zero new persistence, zero new settings needed (already gated by
   `image_intelligence_mode`).
2. **WIRING ONLY** — Replace the single-candidate `send_photo_to_editorial_destination()` call
   with `send_news_with_rich_media()` when ≥2 eligible image candidates exist, falling back to the
   existing single-photo path otherwise (M12's own fallback already does this). Requires flipping
   `rich_media_mode` from `"off"` to at least `"shadow"` for observation first, per this project's
   own established convention, before ever going to `"enforce"`.
3. **NARROW EXTENSION** — Apply the `content_draft_media_items` migration
   (`f2654fa00185`) to the real dev DB (a real, if small, operational step — not "just wiring")
   and flip `video_discovery_mode` to `"shadow"` for a bounded canary to observe real discovery
   hit-rate before any delivery wiring.
4. **WIRING ONLY** (after #3 has real shadow evidence) — Extend the router branch's media
   selection to also consider `content_draft_media_items` video candidates via
   `rank_media_candidates()`'s already-built video role assignment, feeding into the same
   `send_news_with_rich_media()` call from #2 (which already supports trailing video).
5. **NARROW EXTENSION** — Add real logging/observability at the new decision point (which
   candidates were ranked, which role was assigned, why a group vs. single vs. text-only choice
   was made) — extends the existing `router_image_decision`/`router_image_duplicate_skipped`
   log-event convention already in `content_cycle.py`, doesn't invent a new observability system.
6. **NEW CAPABILITY** (not recommended without further authorization) — Any true cross-source
   image borrowing, YouTube/Vimeo thumbnail extraction, or automatic (non-manual-harness) vision
   review gating. None of these have any existing scaffold to extend from safely; each would be a
   genuinely new architectural surface, explicitly out of scope for a "wire what already exists"
   phase.

---

## STOP

Read-only audit complete. No code changed, no config changed, no schema created, no migration
applied, no live canary run. Awaiting direction on which item(s) in §10, if any, to authorize.
