# Video URL Classification Checkpoint

Status: **classification fix implemented and validated with real live evidence. Video Telegram
delivery remains unwired. Media ranking untouched. Not committed. Not deployed.** Direct follow-up
to `docs/video_shadow_checkpoint.md` §8/§11, whose real-world evidence (14/19 = 74% of
hosted-platform "video hints" were channel/user/subscribe links, not actual videos) drove this
narrow corrective phase.

## 1. Exact root-cause fix

**Root cause (confirmed by code inspection before any change):** `classify_video_url()`
(`services/video_discovery.py`) classified a URL as `YOUTUBE`/`VIMEO` based on **hostname alone**
— `_YOUTUBE_HOST_RE`/`_VIMEO_HOST_RE` matched the host, and the function returned immediately with
no inspection of the path or query at all. `extract_article_video_metadata()`'s hosted-platform-
link extraction loop (`for href in anchor_hrefs + iframe_srcs: if classify_video_url(url) in
(YOUTUBE, VIMEO): ...`) therefore treated **any** `<a href>`/`<iframe src>` pointing at a
YouTube/Vimeo host — a footer "Follow us on YouTube" link, a channel/subscribe button, an author's
channel link — identically to a real watch/embed link.

**Fix:** `classify_video_url()` now requires the path/query shape to also identify one of a small,
explicitly bounded set of real video-URL forms before returning `YOUTUBE`/`VIMEO`. A hostname
match alone now falls through to `UNKNOWN` unless the path passes a dedicated shape check
(`_is_youtube_video_path()`, `_is_youtu_be_video_path()`, `_is_vimeo_video_path()`). No other
function in the discovery pipeline changed — every caller of `classify_video_url()` (RSS
extraction, `<video>`/`<source>` tags, Twitter Player Card, hosted-platform-link extraction)
automatically benefits from the same tightened check with zero call-site changes, since they all
route through this one function.

## 2. Accepted / rejected URL rules

**YouTube — accepted (exactly the four forms specified, nothing broader):**
- `youtube.com/watch?v=<id>` (query parsed with `parse_qs`, so extra tracking params/order never
  matter; a non-empty `v` value is required)
- `youtu.be/<id>` (first path segment, non-empty)
- `youtube.com/shorts/<id>`
- `youtube.com/embed/<id>` (also matches on `youtube-nocookie.com`, the same host regex as before)

`<id>` is validated against `^[A-Za-z0-9_-]+$` (non-empty) — deliberately not length-constrained to
the real 11-character YouTube ID convention, since the pre-existing, still-passing test fixture
(`watch?v=abc123`, 6 characters) already relies on a loose length check; length is not a reliable
enough signal to add without risking a false rejection of a legitimate short test/preview id.

**YouTube — rejected (all real false-positive shapes observed live, plus general navigation):**
`/channel/...`, `/user/...`, `/@handle`, `/c/...`, `/feed/...`, `/results`, `/playlist`,
`/subscribe...`, bare `youtube.com`/`youtube.com/`, `/watch` with no or empty `v` param, and any
other unrecognized path.

**Vimeo — accepted:** `vimeo.com/<numeric-id>` (optionally followed by a privacy-hash path
segment, e.g. `vimeo.com/123456789/1a2b3c4d5e`), `player.vimeo.com/video/<numeric-id>`. The
discriminator is that a real Vimeo video id is purely numeric — a username/channel/showcase slug
never is, which is exactly the deterministic, safe signal reused here.

**Vimeo — rejected:** any non-numeric first path segment (`vimeo.com/someuser`,
`vimeo.com/channels/...`, `vimeo.com/showcase/...`), bare `vimeo.com`.

**Not touched/not broadened:** `DIRECT_HOSTED` classification (file-extension based) is completely
unchanged. No new platform, no new discovery method, no network call added anywhere.

## 3. Files changed

- `services/video_discovery.py` — `classify_video_url()` rewritten to require path-shape
  validation for YouTube/Vimeo (previously host-only); three new private helper functions
  (`_is_youtube_video_path`, `_is_youtu_be_video_path`, `_is_vimeo_video_path`); one new import
  (`parse_qs`, stdlib, already-used `urllib.parse` module). No other function in this file
  changed. No DB schema change. No new dependency.
- `tests/test_video_discovery.py` — 20 new tests: 2 YouTube-accepted (extra tracking params +
  fragment, Shorts), 12 YouTube-rejected (channel, user, `@handle`, `/c/`, subscribe-confirmation
  query variant, bare channel slug, feed/subscriptions, playlist, subscribe, search/results, bare
  homepage ×2, malformed/no-id watch ×3), 5 Vimeo (1 accepted with privacy-hash suffix, 4 rejected:
  username, channel, showcase, bare homepage), 1 discovery-integration test (realistic article HTML
  with one real video + 4 navigation links → only the real video becomes a hint).
- `tests/test_rich_media_notifier.py` — 1 new test: the exact real false-positive URL observed
  live, run through the real `classify_video_url()` → `UNKNOWN` → fed through the real, unmodified,
  still-dormant `build_rich_media_plan()` → confirms no `hosted_platform_link` and no video item in
  the media group are produced.
- `scripts/_phase23_1q_video_shadow_canary.py` — runtime cap changed from 75 to 45 minutes for this
  checkpoint's validation run (and the stale "~75 minutes" print label, left over from the previous
  checkpoint's edit, corrected to match — cosmetic only, the enforced value was already correct at
  2700s).
- `scripts/_phase23_1q_video_shadow_post_run_analysis.py` — run-window constants updated to this
  checkpoint's validation run; otherwise unchanged from the prior checkpoint's analysis logic.

## 4. Tests / Ruff / mypy

- `pytest tests/test_video_discovery.py` → **48 passed** (28 pre-existing + 20 new), 0 errors (no
  DB fixtures in this file).
- `pytest tests/test_rich_media_notifier.py` → **11 passed** (10 pre-existing + 1 new), 0 errors.
- `pytest tests/test_video_discovery.py tests/test_video_discovery_persistence.py tests/test_video_discovery_integration.py tests/test_rich_media_notifier.py`
  → **68 passed**, 0 errors — the full existing Phase 19 M10/M12 video test surface, re-verified
  unaffected.
- `ruff check services/video_discovery.py tests/test_video_discovery.py tests/test_rich_media_notifier.py`
  → clean.
- `mypy services/video_discovery.py` → clean (no issues).
- `mypy tests/test_video_discovery.py` → clean (no issues).
- `mypy tests/test_rich_media_notifier.py` → 11 pre-existing errors (10 confirmed present in the
  committed `HEAD` baseline before this checkpoint's edit, via `git show HEAD:... | mypy`; this
  checkpoint's one new test follows the file's own established `_StubCandidate` convention and
  adds exactly one more instance of the same pre-existing error class, `list[_StubCandidate]` vs.
  `list[EditorialImageCandidate]` — not a new category of issue).
- Also independently verified with a standalone 32-case script exercising every accept/reject URL
  form the corrective-phase spec listed (all 32 passed) before formalizing them as pytest tests.

## 5. Short shadow metrics (validation run)

- Window: `2026-08-12T19:33:43Z` → `2026-08-12T20:18:48Z` (2705s, ~45.1 minutes) — within the
  authorized 30–60 minute range.
- Stop reason: `runtime_reached` (clean stop, 0 entries in `errors_log`).
- Cost delta: $0.2843. Collected: 61 events. Analyzed: 40/100. Delivered NEWS items: 6.
- **Total hosted-platform hints: 4**, all YouTube, all `unvalidated_hosted_platform` (as designed
  — never fetched), 0 rejected, spanning 1 distinct event (4 hints on the same story, consistent
  with the earlier run's pattern of the same video link appearing multiple times in one article).
- **Actual-video hints: 4/4 (100%).**
- **Rejected/non-video hosted links: 0/4 (0%).**
- **False-positive rate: 0%** (down from 74% in the pre-fix run).
- YouTube/Vimeo split: 4 YouTube / 0 Vimeo (Vimeo remains unobserved in this project's real source
  mix across both shadow runs — not evidence the Vimeo path itself is broken or fixed, simply
  untested by real traffic so far).
- Direct-hosted video count: **0** (unchanged from the prior run — still no live evidence for this
  half of the pipeline).

## 6. Before / after false-positive rate

| | Before (pre-fix run, ~75 min) | After (this validation run, ~45 min) |
|---|---|---|
| Total hosted-platform hints | 19 | 4 |
| Real video links | 5 (26%) | 4 (100%) |
| Non-video navigation/profile links | **14 (74%)** | **0 (0%)** |

The smaller sample size in the after-run reflects the shorter authorized window and this
particular run's real source mix, not a change in methodology — the metric that matters (§ success
criterion below) is the *ratio*, and it moved from 74% contamination to 0% in this sample.

**Real regression check, re-run on the exact same false-positive URLs found in the before-run:**
all 14 (e.g. `youtube.com/channel/UChjRM_qQAaOAiLNbOGbYcRA`, `youtube.com/@mkbhd`,
`youtube.com/c/9to5google`, `youtube.com/user/techcrunch`) now classify as `UNKNOWN`; all 5 real
watch links from that same run (`youtube.com/watch?v=o4SSoURPODY`, etc.) still classify as
`YOUTUBE` — verified directly, not inferred.

## 7. Remaining ambiguous URL forms

None encountered in either shadow run. Reported honestly rather than invented: the real traffic
seen so far only exercised bare watch links and bare channel/profile/subscribe links — clearly one
category or the other, never a borderline case (e.g. a `youtube.com/live/<id>` live-stream
permalink, a `youtube.com/clip/<id>` clip-share link, or a Vimeo showcase page that happens to
embed a single video) hasn't appeared in real data yet. Per the explicit instruction not to expand
heuristics blindly, no additional forms were added speculatively — if a genuinely ambiguous form
surfaces in future live traffic, it should be reported and evaluated on real evidence at that time,
not guessed at now.

## 8. Direct-hosted observations

Unchanged from the prior checkpoint: **zero direct-hosted candidates observed** across both shadow
runs (pre-fix ~75 min + this validation ~45 min, ~120 minutes of combined real shadow evidence).
This classification fix does not touch `DIRECT_HOSTED` handling at all (file-extension-based,
already narrow), and per this phase's explicit scope, direct-hosted delivery/eligibility remains a
separate, still-open decision requiring its own live evidence — not addressed here.

## 9. Recommendation

**HOSTED VIDEO DISCOVERY CLEAN — READY FOR NEXT STEP.**

The specific, blocking correctness defect identified in the Video Shadow Checkpoint —
non-video YouTube/Vimeo navigation/profile links entering the video candidate pipeline — is fixed
and confirmed against both synthetic test cases (32/32) and real, previously-observed false-positive
URLs (14/14 now correctly rejected, 5/5 real videos still correctly accepted), and reconfirmed with
a fresh live shadow sample showing 0% false positives (down from 74%).

This recommendation covers **hosted-platform link discovery/classification only**. It does **not**
extend to:
- Wiring hosted-platform video into live Telegram delivery (still dormant, not authorized this
  phase).
- Direct-hosted video eligibility (still zero live evidence — a separate, later decision).
- Media ranking changes for video (`MediaRankingInput.quality_score` still has no real source for
  video — the gap disclosed in the prior checkpoint remains unaddressed, out of this phase's scope
  by explicit instruction).

Nothing was committed. Nothing was deployed. No Telegram video delivery was implemented.
`video_discovery_mode` was restored to `"off"` in-process after the validation run; `.env` was
never touched.
