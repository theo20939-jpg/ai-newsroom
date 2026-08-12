# Video Shadow Checkpoint

Status: **discovery/validation evidence only. No Telegram video delivery implemented. Not
committed. Not deployed.** Resumes video activation from the Step 2 review state per the "safe
video activation sequence," picking up after the media-quality corrective phase completed and was
validated separately (`docs/media_quality_checkpoint.md`).

## 1. DB migration result and revision

**Before this session's action:** `alembic current` already reported `f2654fa00185` — this
migration was applied in an earlier part of this same multi-phase session, before video work was
paused for the media-quality corrective phase. No migration command was re-run, since the target
revision was already reached; running `alembic upgrade f2654fa00185` again would have been a
no-op.

**Verification performed this checkpoint (read-only):**
- `alembic heads` → `3f37cf34109d`. The dev DB is **behind head by three unrelated migrations**
  (`94fd27f7d129` add media vision reviews table, `3c22be05f4e5` add story memory v2 shadow
  columns, `3f37cf34109d` add stories updated_at index) — none of these are video-related, and per
  the explicit "do not alter unrelated migrations" instruction, they were **left unapplied**, not
  touched in any way.
- Inspected the real `content_draft_media_items` table via SQLAlchemy `inspect()` against the live
  dev DB connection: all 15 columns, both indexes (`ix_content_draft_media_items_event_id`,
  `ix_content_draft_media_items_content_draft_id`), and both foreign keys
  (`event_id → news_events.id`, `content_draft_id → content_drafts.id`) match the migration file
  (`database/migrations/versions/f2654fa00185_add_content_draft_media_items_table.py`) exactly —
  no conflict, no drift.

**After:** unchanged — `f2654fa00185`. No new migration created.

## 2. Exact code files changed this checkpoint

- `scripts/_phase23_1q_video_shadow_canary.py` — runtime cap changed from `2 * 60 * 60` (2 hours)
  to `75 * 60` (~75 minutes), per this checkpoint's explicit "shorter bounded run" instruction; two
  print-statement text updates to match. No other logic changed — every safety control (hard
  delivery cap, cost cap, max-analyzed cap, in-process-only settings override with restore-on-exit,
  destination assertion) is untouched from the already-established canary harness.
- `scripts/_phase23_1q_video_shadow_post_run_analysis.py` — new, read-only analysis script (see §5
  onward). Makes zero writes, zero Telegram calls, never imports `worker/content_cycle.py`.

**Not changed this checkpoint** (already existed from the earlier, paused part of this session —
re-verified, not re-implemented):
- `services/video_discovery_persistence.py::get_video_candidates_for_event()` /
  `EligibleVideoCandidate`.
- `tests/test_video_discovery_integration.py`'s four `get_video_candidates_for_event` tests.

## 3. Tests / Ruff / mypy

- `pytest tests/test_video_discovery_integration.py` → **6 passed, 0 errors** (all six tests in
  the file, including the pre-existing shadow-mode/off-mode persistence tests).
- `ruff check services/video_discovery_persistence.py tests/test_video_discovery_integration.py`
  → clean.
- `mypy services/video_discovery_persistence.py` → clean (no issues).
- `mypy tests/test_video_discovery_integration.py` → clean (no issues).
- `ruff check scripts/_phase23_1q_video_shadow_canary.py scripts/_phase23_1q_video_shadow_post_run_analysis.py`
  → clean.
- `mypy scripts/_phase23_1q_video_shadow_post_run_analysis.py` → clean.
- `mypy scripts/_phase23_1q_video_shadow_canary.py` → one pre-existing `arg-type` note in
  `_instrument_send_media_group`'s loosely-typed `object` kwargs handling (present before this
  checkpoint's two edits; this project's established convention does not fully type-annotate
  one-off canary scripts — not a production code path, not touched by this checkpoint's changes).

## 4. Canary runtime / cost / volume

- Window: `2026-08-12T17:13:14Z` → `2026-08-12T18:28:37Z` (4524s, ~75.4 minutes).
- **Stop reason: `runtime_reached`** — the bounded window elapsed cleanly; no safety cap tripped
  early, `errors_log` is empty (0 entries) for the entire run.
- Cost delta: **$0.4318** (baseline $10.2101 → final $10.6419), well under the $2.00 cap.
- Collection: 3 collection ticks, `events_created` = 60 + 22 + 19 = **101** total collected;
  `sources_processed` ≈ 464/461/465 per tick (a steady ~4-6% `sources_failed` rate each tick,
  consistent with this project's normal baseline, not video-related).
- Analysis: **60/100** analyzed (stopped by the max-analyzed cap on its own schedule, not an
  error).
- Delivery: **12 NEWS items delivered** (`notified=12`): 6 single-photo, 2 media-group, 4
  text-only. `cap_attempted=10/20` (the hard-cap wrapper counts `send_message`/`send_photo` only —
  the 2 `send_media_group` sends are outside its count, the same disclosed gap already flagged in
  `docs/media_quality_checkpoint.md` §7, not new).
- Destination assertion (`chat_id`/`message_thread_id` match the approved NEWS route for every
  recorded send) passed for all 12 sends.
- Settings restored on exit, in-process only, confirmed by the script's own printed confirmation
  lines — `.env` was never touched.

## 5. Video discovery hit rate

- **19 video-hint rows** persisted to `content_draft_media_items` during the window.
- **7 of 60 analyzed events (11.7%)** produced at least one video hint.
- Hints-per-story distribution: 1 hint → 3 stories, 2 hints → 1 story, 4 hints → 2 stories, 6
  hints → 1 story.

## 6. Discovery-method distribution

| Method | Count |
|---|---|
| `hosted_platform_link_in_article` | 19 |
| RSS enclosure/`media_content[video]` | 0 (did not occur) |
| `og:video`/`og:video:secure_url` | 0 (did not occur) |
| HTML `<video>`/`<source>` | 0 (did not occur) |
| Twitter Player Card | 0 (did not occur) |

Only one discovery method fired in this sample — reported as observed, not forced or padded.

## 7. Platform/type distribution

| Platform | Count |
|---|---|
| YouTube | 19 |
| Vimeo | 0 (did not occur) |
| Direct-hosted (any container) | 0 (did not occur) |

## 8. Validation results and rejection reasons

| Validation status | Count |
|---|---|
| `unvalidated_hosted_platform` | 19 |
| `valid` | 0 (did not occur — no direct-hosted candidates this run) |
| `rejected` | 0 (did not occur) |

No rejection error codes to aggregate — zero rejections occurred, honestly reported rather than
fabricated.

### Key finding — hosted-platform-link discovery has no path-based filtering (real, measured)

Classifying the 19 real persisted URLs by path shape (not host):

| Category | Count |
|---|---|
| Real watch/embed links (`/watch?v=`, `youtu.be/`, `/embed/`) | **5 (26%)** |
| Channel/user/handle/subscribe links — **not actual videos** | **14 (74%)** |

Sample of the false-positive links (real data, this run): `youtube.com/channel/UChjRM_qQAaOAiLNbOGbYcRA`,
`youtube.com/9to5mac`, `youtube.com/c/9to5mac?sub_confirmation=1`, `youtube.com/@mkbhd`,
`youtube.com/@DwarkeshPatel`, `youtube.com/c/9to5google`, `youtube.com/user/techcrunch`,
`youtube.com/user/3DNewsRU`.

**Root cause (confirmed by code inspection, `services/video_discovery.py`):**
`classify_video_url()` matches on **host only** (`_YOUTUBE_HOST_RE`/`_VIMEO_HOST_RE`, never
inspects the path). `extract_article_video_metadata()`'s hosted-platform-link extraction then
treats **every** `<a href>`/`<iframe src>` whose host matches YouTube/Vimeo as a video hint —
a footer "Follow us on YouTube" link, a byline's channel link, or a subscribe button is
indistinguishable, at persistence time, from a real watch/embed link. This is a genuine
discovery-quality defect, the same class of problem already found and fixed for images in the
media-quality corrective phase — not fixed here, since the current authorization is
discovery/shadow evidence only, not a code change to the discovery logic.

**Demonstrated with real code, read-only** (`build_rich_media_plan()`, dormant, never called with
a real `video_hint` in live delivery today): feeding one of the real persisted false-positive
channel links through the actual, unmodified function produces the caption line
`"\n\nVideo: https://www.youtube.com/channel/UChjRM_qQAaOAiLNbOGbYcRA"` — exactly the kind of
broken, misleading output that would ship if this mechanism were wired live today without a fix.

## 9. Image/video coexistence statistics

All 7 events that produced a video hint also had at least one usable image candidate
(`eligible_for_editorial=True`):

| Category | Count |
|---|---|
| Video + usable image(s) | 7 |
| Video only / no usable image | 0 |
| Usable image(s) only (no video) | not computed — out of this checkpoint's scope (would require scanning all 60 analyzed events, not just the 7 with video) |
| Neither | not computed — same reason |

In this sample, video never appeared without an image already available for the same story —
relevant to future media-policy decisions about when video should compete with vs. supplement an
existing image.

## 10. Hypothetical delivery-eligibility results

- **Direct-hosted candidates considered: 0** — none were discovered in this run, so
  `rank_media_candidates()`'s numeric eligibility formula (`quality_score >= 30`) could not be
  exercised against any real direct-hosted video data this checkpoint. Reported as unobserved,
  not simulated with fabricated candidates.
- **Disclosed architectural gap, discovered while attempting this analysis:**
  `MediaRankingInput.quality_score` is a required field, but **no quality-scoring pipeline exists
  for video candidates anywhere in this codebase** (`services/image_quality.py`'s `QualitySignals`
  is image-only). Any hypothetical numeric eligibility count for direct-hosted video would have to
  substitute a fabricated placeholder score — done once, clearly labeled as a placeholder never
  used for real selection, purely to confirm the `video_validation_status == "rejected"` gate
  works mechanically; not treated as a real eligibility measurement.
- **Hosted-platform (YouTube/Vimeo) candidates: 19, never gated by ranking eligibility at all** —
  confirmed by code inspection: `build_rich_media_plan()`/`send_news_with_rich_media()` append the
  hosted-platform caption link unconditionally whenever a non-`DIRECT_HOSTED` `video_hint` is
  supplied; `rank_media_candidates()` is never consulted for that path. This means the §8 filtering
  defect above is **not** something the existing ranking model would catch even after wiring —
  a channel-link false positive would ship as-is regardless of ranking, since ranking is bypassed
  entirely for hosted-platform video.

## 11. Representative real examples

1. **Valid direct-hosted:** not observed this run (reported honestly, not forced).
2. **Hosted-platform, real watch link:** event "Google DeepMind launches SL2T, a multilingual
   sign-language-to-text model debuting on the Pixel 11 in Gboard and Live"
   (techmeme.com/260812/p35#a260812p35) → `hosted_platform_link_in_article` → `youtube.com` watch
   link → `unvalidated_hosted_platform` (by design, never fetched) → persisted → hypothetically
   would produce a valid caption link if wired.
3. **Hosted-platform, false-positive channel link:** event "SpaceXAI releases Grok 4.6..."
   (9to5mac.com) → `hosted_platform_link_in_article` → `youtube.com/channel/UChjRM_qQAaOAiLNbOGbYcRA`
   → `unvalidated_hosted_platform` → persisted → hypothetically would produce a **broken/misleading**
   caption line reading "Video: https://www.youtube.com/channel/..." if wired today, demonstrated
   with the real `build_rich_media_plan()` call in §8.
4. **Rejected:** not observed this run (reported honestly, not forced).

## 12. Performance/reliability impact

- Zero entries in `errors_log` across the entire ~75-minute run.
- Video discovery is best-effort and exception-guarded at two independent layers
  (`services/article_acquisition.py`'s `try/except Exception` around
  `extract_article_video_metadata()`, and a separate guard around persistence inside a
  `session.begin_nested()` SAVEPOINT) — confirmed by code inspection, and consistent with zero
  observed persistence failures this run.
- No unusual bandwidth/load pattern: zero direct-hosted `safe_fetch()` validation calls occurred
  this run (no direct-hosted candidates were discovered), so the bounded-fetch validation path
  (`validate_direct_hosted_video()`) was not exercised at all in this window — a genuine gap in
  this run's evidence coverage, not a failure.
- No cost anomaly attributable to video discovery — video extraction runs against already-fetched
  article HTML (zero additional network requests for discovery itself; the *only* video-specific
  network calls would be YouTube/Vimeo — none, since those are validated by URL pattern only, never
  fetched — and direct-hosted validation fetches, of which there were zero this run).

## 13. Remaining gaps

- **Telegram-side URL acceptance:** untested this run — zero direct-hosted candidates means
  `bot.send_video()`/`InputMediaVideo` was never exercised against a real Telegram API call
  (correctly, since delivery remains unwired and shadow mode must never reach Telegram).
- **Poster fallback:** no poster/thumbnail extraction exists anywhere in the video pipeline today
  (confirmed by code inspection — `NativeVideoHint`/`VideoValidation` carry no thumbnail field);
  not evaluated this run since it's not implemented at all yet.
- **Hosted-platform handling — newly discovered, significant:** the §8 finding is the most
  important result of this checkpoint. 74% of hosted-platform "video hints" in this real sample
  were not actual videos. Wiring the existing dormant caption-link mechanism today, without first
  adding path-based filtering to `classify_video_url()`/`extract_article_video_metadata()`, would
  ship broken/misleading "Video: <channel link>" text on live NEWS posts — a real product-quality
  regression, not a hypothetical one.
- **No quality-scoring pipeline for video** (§10) — a structural gap that must be resolved (or an
  explicit alternative eligibility rule must be designed) before direct-hosted video can be
  numerically ranked at all, since `MediaRankingInput.quality_score` has no real source for video
  today.
- **Zero direct-hosted evidence this run** — the entire direct-hosted validation path
  (`validate_direct_hosted_video()`, container sniffing, byte-size capping) remains unexercised
  by real traffic in this checkpoint; its real-world reliability is still unknown.

## 14. Recommendation

**VIDEO PIPELINE NEEDS NARROW FIX FIRST.**

Specifically and narrowly:
1. Add path-based filtering to the hosted-platform-link discovery path (`services/video_discovery.py`)
   before any live wiring of the dormant caption-link mechanism — e.g. require `/watch?v=`,
   `youtu.be/`, or `/embed/` for YouTube, and a numeric video-id path for Vimeo, rejecting
   channel/user/handle/subscribe links at classification time. This is the single most
   consequential, concretely evidenced fix from this checkpoint.
2. Separately, **direct-hosted video needs more shadow evidence** — zero real candidates were
   observed in this ~75-minute window, so its validation reliability, byte-size distribution, and
   container mix remain unmeasured. A longer or differently-timed shadow run (or one that happens
   to hit sources with embedded native video) would be needed before any eligibility claim can be
   made for that half of the pipeline.
3. A quality-scoring source for video must be designed before `rank_media_candidates()` can
   meaningfully gate direct-hosted video eligibility — today that field has no real input.

No Telegram video delivery was implemented. Nothing was committed. Nothing was deployed.
`video_discovery_mode` was restored to `"off"` in-process; `.env` was never touched.
