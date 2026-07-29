# Phase 16 M3 — Quality Gate, Exact Deduplication, and Perceptual Near-Duplicate Detection — Report

Branch: `feature/phase16-image-intelligence`
Checkpoint: `checkpoint/phase16-m3` (created at the end of this milestone)
Prior checkpoint: `checkpoint/phase16-m2`

## 1. M3 objective

Add a deterministic, zero-AI editorial-quality and duplicate-control layer on top of M2's
technically-validated `ImageCandidate` objects: hard/soft quality rules, exact (SHA-256)
deduplication, perceptual near-duplicate detection, a transparent 0–100 quality score, and a final
per-candidate `QualityStatus` (`accepted` / `rejected_quality` / `duplicate_exact` /
`duplicate_near` / `review`). All analysis reuses the exact image bytes M2 already fetched — no
additional network request per candidate. Bytes are never persisted. Text-only `ContentDraft`
delivery is never blocked by anything in this module.

## 2. Starting M2 architecture

M2 left `services/image_intelligence.py::run_shadow_discovery()` as the single per-event
orchestration entry point: it reconstructs M1 native-media hints, optionally fetches the article
page and extracts OG/Twitter/JSON-LD metadata hints (`services/article_metadata.py`), consolidates
and prioritizes candidate URLs, fetches each one through the SSRF-safe `integrations/http/
safe_fetch.py` boundary, and runs `services/image_validation.py::validate_image_bytes()` to produce
`TechnicalValidation` (dimensions, format, SHA-256, pixel count, byte size, `error_code`). Only
candidates that reach `ImageCandidateStatus.VALIDATED` carry a non-null `TechnicalValidation`.
`ImageIntelligenceResult` aggregates per-event counts and the full candidate list. Everything is
in-memory Pydantic; nothing is written to the database. `IMAGE_INTELLIGENCE_MODE` (`off`/`shadow`)
remains the single gate; `off` short-circuits before any network access.

## 3. Image-byte lifecycle traced for M3

`_fetch_and_validate_candidate()` in `services/image_intelligence.py` holds `fetch_result.body:
bytes` in a local variable for the duration of one candidate's processing, calls
`validate_image_bytes()` on it, and — as of M3 — if that returns `VALIDATED`, immediately calls
`services.image_quality.analyze_candidate(fetch_result.body, candidate=updated)` on the **same**
bytes before the function returns and the bytes go out of scope. No bytes are written to disk, no
bytes are attached to any long-lived object, no bytes cross the module boundary a second time. The
only "extra" cost M3 adds is one additional in-memory Pillow decode (grayscale resize for the
perceptual hash, plus a cheap 32×32 dominant-color resize) — zero additional HTTP requests, verified
directly in the bounded network validation (§24): total image downloads for a fixed 20-article,
5-images-per-article sample matched M2's own prior bounded-validation download count exactly.

## 4. Quality-result contract

`schemas/image_candidate.py` gained (additive-only; every M1/M2 field and every M1/M2 test still
passes unmodified):

- `QualityStatus` enum: `accepted`, `rejected_quality`, `duplicate_exact`, `duplicate_near`,
  `review`.
- `ResolutionBand` enum: `tracking`, `icon`, `weak`, `adequate`, `good`.
- `AspectRatioBand` enum: `extreme_tall`, `portrait`, `square`, `editorial_landscape`,
  `wide_banner`, `extreme_wide`.
- `QualitySignals` — `resolution_band`, `aspect_ratio_band`, and six `possible_*` booleans
  (`tracking_pixel`, `icon`, `logo`, `avatar`, `banner`, `placeholder`). Deliberately named
  `possible_*`, never `confirmed_*` — every signal here is a conservative, reviewable hint, not a
  ground-truth classification.
- `DeduplicationInfo` — `exact_hash`, `perceptual_hash`, `exact_cluster_id`,
  `perceptual_cluster_id`, `duplicate_of`, `hamming_distance`, `is_representative`.
- `QualityValidation` (`version: Literal["m3"] = "m3"`) — `status`, `quality_score` (0–100),
  `quality_components`, `quality_penalties`, `hard_rejection_reasons`, `quality_warnings`,
  `signals`, `deduplication`, `duration_ms`.
- `ImageCandidate.schema_version` widened to `Literal["m1", "m2", "m3"]`; new field
  `quality_validation: QualityValidation | None = None`.
- `ImageIntelligenceResult.version` widened to `Literal["m1", "m2", "m3"]`; five new
  `Field(default=0, ge=0)` counters: `candidates_quality_accepted`, `candidates_rejected_quality`,
  `candidates_duplicate_exact`, `candidates_duplicate_near`, `candidates_review`.

All new models keep the repository convention: `model_config = ConfigDict(frozen=True,
extra="forbid")`.

## 5. Hard rejection rules

Evaluated in `services/image_quality.py::_assemble_analysis()`, conservative and combination-of-
evidence where evidence is ambiguous alone:

1. **`tracking_pixel_dimensions`** — shortest side ≤ 3px OR total pixel count ≤ 16 (catches 1×1,
   1×2, 2×2, etc. tracking pixels regardless of exact shape).
2. **`favicon_dimensions`** — both sides ≤ 64px (and not already a tracking pixel).
3. **`favicon_with_url_evidence`** — both sides ≤ 128px AND the URL/alt-text matches an icon or
   tracking token (a slightly larger image is only hard-rejected on dimensions alone up to 64px;
   between 64px and 128px it needs corroborating URL evidence before hard rejection).
4. **`extreme_aspect_ratio`** — ratio ≤ 0.05 or ≥ 20.0 (pathological slivers, not ordinary wide/tall
   editorial crops).
5. **`tracking_pixel_evidence`** — a tracking/pixel/beacon/spacer token AND resolution in the
   `tracking`/`icon` band (token alone, on a normal-sized image, is not hard rejection evidence).
6. **`placeholder_strong_evidence`** (`strong_placeholder`) — a placeholder/default/no-image token
   AND (resolution in `tracking`/`icon` band OR the image is ≥97% one dominant color). A
   placeholder token on a normal-sized, visually varied image is a soft warning only (§7), never a
   hard rejection — this is deliberate: a legitimately named `default-hero.jpg` that happens to be
   a real, large, colorful editorial photo must not be discarded on filename alone.

## 6. Soft penalty rules

Never independently sufficient for rejection; each subtracts from the score and adds a
`quality_warnings` entry:

| Signal | Penalty | Trigger |
|---|---|---|
| `possible_logo` | −15 | logo/logotype token, OR (`adequate` resolution AND `square` aspect AND ≥60% dominant color) |
| `possible_avatar` | −10 | avatar/profile/author/userpic token |
| `possible_banner` | −12 | banner/ad/advert/sponsor token, OR aspect ratio in the `extreme_wide` band (>5.0) |
| `possible_icon` | −10 | icon/favicon/sprite token (and not already hard-rejected) |
| `possible_placeholder` | −20 | placeholder/default token, present but not meeting the "strong" combination in §5 |
| `possible_thumbnail` | −5 | thumbnail/thumb token (informational only — thumbnails are commonly legitimate, smaller editorial crops) |

`possible_banner`'s rule was tightened during bounded real-network validation (§25) — see the
false-warning finding there for the specific evidence.

## 7. Review rules

`services/image_intelligence.py::_decide_quality_status()` assigns `QualityStatus.REVIEW` (rather
than a hard accept/reject) when: the analysis could not decode the image (`decode_error` set, e.g.
an unexpected internal failure on an already-VALIDATED candidate); `possible_logo` or
`possible_banner` fired (both signals plausibly indicate non-editorial content but are not reliable
enough alone to auto-reject); or the candidate has a non-null Hamming distance to another cluster
that falls inside the review band but outside the auto-duplicate band (§17). `REVIEW` never blocks
text-only delivery — it is a downstream advisory status only.

## 8. Dimension thresholds and evidence

`resolution_band(width, height)` (shortest side and total pixel count):

- `tracking`: shortest side ≤ 3px OR total pixels ≤ 16
- `icon`: shortest side ≤ 64px
- `weak`: shortest side < 300px
- `adequate`: 300px ≤ shortest side < 600px
- `good`: shortest side ≥ 600px

Thresholds were set from a combination of the M2 bounded-validation sample (real og:image/
twitter:image dimensions observed: 96×96 avatar thumbnails, 1200×630 canonical OG hero size,
1200–2160px-wide hero photos) and conventional web favicon/icon sizes (16/32/48/64px). `600px`
shortest side as the "good" floor matches the common 1200×630 OG-image convention (630 > 600) while
still rewarding slightly smaller but still substantial photos.

## 9. Aspect-ratio bands

`aspect_ratio_band(width / height)`:

- `extreme_tall`: ratio ≤ 0.2
- `portrait`: ratio ≤ 0.75
- `square`: ratio ≤ 1.33
- `editorial_landscape`: ratio ≤ 2.2
- `wide_banner`: ratio ≤ 5.0
- `extreme_wide`: ratio > 5.0

`editorial_landscape`'s 2.2 ceiling comfortably covers the canonical 1200×630 OG-image ratio
(≈1.90) and common 16:9/21:9 hero crops, while `wide_banner` (2.2–5.0) captures genuinely
banner-shaped images without being pathological. Only `extreme_wide` (>5.0) is treated as
suspicious from ratio alone (§25).

## 10. Metadata/URL signals

`_searchable_text()` combines `alt_text` with the URL's **path and query only** — the hostname is
deliberately excluded, so a CDN subdomain that happens to contain a generic word (e.g.
`logo-cdn.example.com` serving entirely legitimate hero photos) is never flagged. Token matching
uses `\b`-word-boundary, case-insensitive compiled regexes (`_compile_token_pattern`), verified
directly: `"catalogo"` does **not** match the `logo` token (no boundary between shared word
characters), while `"app-icon-192.png"` **does** match the `icon` token (`-` is a non-word
boundary). Token sets include both English and Russian words (`лого`, `аватар`, `промо`, `реклама`,
`заглушка`) since the collector ingests Russian-language sources.

## 11. Placeholder heuristics

A placeholder token alone → `possible_placeholder` (soft, §6). A placeholder token **combined**
with either tiny dimensions or ≥97% single-dominant-color content → `placeholder_strong_evidence`
(hard reject, §5). Dominant-color ratio is computed via a cheap 32×32 nearest-neighbor resize +
color histogram (`_dominant_color_ratio`) — deliberately used only as one corroborating signal among
several, per the task brief's explicit warning against classifying minimalist illustrations as
placeholders from color statistics alone (a solid-color minimalist logo/illustration with a
placeholder-sounding filename is exactly the case a single-signal rule would misclassify).

## 12. Logo/icon heuristics

`possible_logo`: an explicit logo/logotype token, OR the combination of `adequate` resolution +
`square` aspect ratio + ≥60% dominant color (a small-to-medium, mostly-flat-colored square image —
a common logo shape — even without a matching filename). `possible_icon`: an icon/favicon/sprite
token, only when the candidate was not already hard-rejected (an icon-shaped image that's already
hard-rejected on dimensions doesn't need a second, redundant soft flag).

## 13. Avatar heuristics

`possible_avatar` requires an explicit avatar/profile/author/userpic token — there is no
dimension-only fallback (unlike logo), since small square images are common for entirely legitimate
reasons (product shots, icons already handled separately) and avatar-specific vocabulary is a much
more reliable signal than shape alone. Confirmed against real data in §25: three 96×96 images from
9to5google.com/9to5mac.com/9to5toys.com all correctly matched an avatar/author token and were
soft-penalized, not hard-rejected.

## 14. Banner/ad heuristics

`possible_banner`: an explicit banner/ad/advert/sponsor token, OR an aspect ratio in the
`extreme_wide` band (>5.0, i.e. genuinely pathological banner-strip proportions such as classic
970×90/728×90 leaderboard ad units). Originally also fired on the `wide_banner` band (2.2–5.0)
alone; this was tightened after bounded validation showed it flagging a legitimate 1019×438
editorial hero image with zero ad/banner token evidence (§25) — the task brief's own explicit
"use multiple independent signals before strong penalty" guidance for wide editorial images.

## 15. Exact deduplication

`services/image_deduplication.py::_build_exact_groups()` groups a single event's candidates by
`TechnicalValidation.sha256` (M2's own hash, unmodified). Every group's members other than the
chosen representative (§19) receive `QualityStatus.DUPLICATE_EXACT`, `hamming_distance=0`, and
`duplicate_of` pointing at the representative's `candidate_id`. This is exact, deterministic,
byte-identical detection — no perceptual comparison involved.

## 16. Perceptual-hash algorithm

`compute_dhash()` implements a **difference hash (dHash)**: EXIF-orientation-normalize, convert to
grayscale, resize to 9×8, and set each of the 64 output bits to 1 if a pixel is brighter than its
right neighbor, 0 otherwise — yielding a 64-bit hash rendered as 16 hex characters. Chosen over
average-hash and pHash because: (a) it is robust to resizing and JPEG recompression (both preserve
relative local gradients even as absolute pixel values shift); (b) it is naturally **sensitive to
cropping** — a crop changes which gradients exist at all, so a genuinely different crop is correctly
*not* collapsed into the same cluster as the original, satisfying the task brief's explicit
requirement that crops must not be blindly merged; (c) it needs only Pillow (no numpy/opencv —
verified by a dedicated test that AST-parses the module's own imports); (d) it is cheap — one
72-pixel resize and 64 integer comparisons per candidate.

## 17. Distance thresholds

`AUTO_DUPLICATE_MAX_DISTANCE = 4`, `REVIEW_MAX_DISTANCE = 12`. Calibrated empirically
(`scripts/phase16_m3_offline_calibration.py` plus a dedicated scratch calibration script) against a
synthetic fixture set derived from a real Pillow-rendered scene (gradient + shapes), producing one
original plus: an exact byte copy, a LANCZOS-resized copy, three JPEG recompressions (quality 85/60/
40), a small (~10%-edge) crop, a large (~25%-edge) crop, a brightness-adjusted copy, a text-overlay
variant, a 90°-rotated copy, and a genuinely distinct second scene. Measured Hamming distances:
identical / resized / recompressed / small-crop / brightness-adjusted variants all measured ≤4; a
moderate text overlay measured 5; the 25%-edge crop measured 15; unrelated/distinct scenes measured
22–43. This is why the automatic-merge threshold is 4 (deliberately tighter than the "10" some
libraries default to) and the review band extends to 12 — erring toward flagging `review` rather
than silently over-merging two editorially distinct images, per the task brief's own stated
priority. Real-world confirmation: the bounded network validation (§24/§25) found zero likely false
duplicates across 14–15 real merges, all of which paired identical-dimension og:image/twitter:image/
JSON-LD URLs pointing at the same underlying asset for the same article.

## 18. Near-duplicate clustering

`_build_near_clusters()` implements **representative-based ("star") clustering**: exact-duplicate
groups are first reduced to one representative each, then representatives are processed in
quality-descending order (§19's sort key); each one is compared only against already-established
clusters' own representatives (never against arbitrary prior chain members), and merges into the
closest cluster within `AUTO_DUPLICATE_MAX_DISTANCE`, or founds a new cluster if none qualifies.
This deliberately avoids naive transitive over-merging (A~B~C merging A and C despite A and C being
distant from each other) — every merge decision is anchored to a stable, quality-chosen
representative, not a potentially-drifting chain.

## 19. Representative selection

`_representative_sort_key()` (ascending — smaller is "better"): `-pixel_count` (prefer higher
resolution), `-aspect_ratio_component` (prefer more editorial aspect ratios per §6's `_ASPECT_RATIO_
COMPONENT` table), `-metadata_confidence_component` (prefer stronger discovery-method provenance),
`-byte_size` (weak tie-break, prefer larger — as-is, without asserting any general JPEG-vs-PNG
byte-size relationship, which the offline calibration script's own commentary explicitly notes is
pattern-dependent), `discovery_order` (earlier-discovered wins remaining ties), `candidate_id`
(final deterministic tie-break). Applied identically for exact-group representative selection and
near-cluster representative selection.

## 20. Quality-score formula

`raw_score = sum(quality_components.values()) + sum(quality_penalties.values())`, then clamped to
`[0, 100]`. Components (each independently capped, summing to at most 100):

- `resolution` (0–40): `tracking`=0, `icon`=5, `weak`=15, `adequate`=28, `good`=40
- `aspect_ratio` (0–20): `extreme_tall`=5, `portrait`=15, `square`=15, `editorial_landscape`=20,
  `wide_banner`=12, `extreme_wide`=5
- `technical_integrity` (0–20): 20 if no declared dimensions to cross-check (nothing contradicted),
  20 if declared dimensions are present and match actual decoded dimensions within a 5%/2px
  tolerance, 10 if they meaningfully disagree, 10 (neutral, never a bonus) if no technical
  validation is available at all
- `metadata_confidence` (5–20): from `_DISCOVERY_METADATA_CONFIDENCE` per `ImageDiscoveryMethod`
  (Telegram photo/document and OG secure-image score highest at 20; generic/unknown native hints
  score lowest at 5), +2 (capped at 20) if `alt_text` is present and ≥3 characters

Penalties (§6) are then subtracted. A clean 1200×630 editorial hero with matching declared
dimensions and high-confidence discovery scores 98–100; a 96×96 avatar-flagged thumbnail scores
around 58; a hard-rejected candidate's score is not meaningful (hard rejection short-circuits to
`rejected_quality` regardless of the numeric score).

## 21. Files changed

- `schemas/image_candidate.py` — additive quality/dedup/status contract (§4)
- `services/image_quality.py` (new, ~350 lines) — bands, tokens, hard/soft rules, dHash, scoring
- `services/image_deduplication.py` (new, ~220 lines) — exact grouping, near-duplicate star
  clustering, representative selection
- `services/image_intelligence.py` — `_fetch_and_validate_candidate`/`_validate_selected_candidates`
  thread `QualityAnalysis` alongside each `ImageCandidate`; new `_decide_quality_status()` and
  `_finalize_quality()`; `run_shadow_discovery()` computes M3 counts and sets `version="m3"`
- `capabilities/executor.py` — unchanged; already calls `run_shadow_discovery()`, which now
  internally performs the M3 stage
- `tests/test_image_quality.py` (new, 48 tests)
- `tests/test_image_deduplication.py` (new, 33 tests)
- `tests/test_image_intelligence_m3.py` (new, 17 tests)
- `scripts/phase16_m3_offline_calibration.py` (new, kept per repo precedent)
- `scripts/phase16_m3_bounded_network_validation.py` (new, kept per repo precedent)
- `scripts/phase16_m3_controlled_shadow_validation.py` (new, kept per repo precedent)

## 22. Tests and exact results

- `tests/test_image_quality.py`: 48 passed
- `tests/test_image_deduplication.py`: 33 passed
- `tests/test_image_intelligence_m3.py`: 17 passed
- M3 subtotal: **98 passed**
- Combined `-k image` selection across M1/M2/M3 image-intelligence test files: **215 passed**
- Full repository suite (`python -m pytest -q`): **1462 passed, 15 failed** — the 15 failures are
  the pre-existing baseline unrelated to Phase 16 (DB-pollution/environment-mismatch failures in
  `test_capability_executor.py`, `test_content_generation_integration.py`,
  `test_content_worker_cycle.py`, `test_editorial_scoring.py`, `test_fact_safety.py` — all failing
  on assertions like "zero provider calls" against a shared, already-polluted test database, not on
  any Phase 16 code path). No test outside the Phase 16 image-intelligence files was touched by this
  milestone.
- `ruff check` on all M3-added/modified files: all checks passed
- `mypy` on `services/image_quality.py`, `services/image_deduplication.py`,
  `services/image_intelligence.py`, `schemas/image_candidate.py`, `capabilities/executor.py`: no
  issues found

## 23. Offline calibration

`scripts/phase16_m3_offline_calibration.py` generates 13 programmatic fixture categories (tracking
pixel, favicon, app icon, publisher logo, author avatar, social placeholder, wide banner, normal
landscape, normal portrait, product screenshot, infographic, branded launch artwork, unrelated
image) plus 4 deduplication variants (exact, resized, recompressed, cropped) entirely with Pillow —
no committed real or copyrighted images. Results (post-tuning, §14): tracking pixel and favicon
correctly hard-rejected (score floors reflect neutral-component scoring, not a meaningful ranking
once hard-rejected); app icon/publisher logo/author avatar correctly soft-flagged, not hard-rejected;
the wide-banner fixture (970×90, ratio 10.8, `extreme_wide` band, URL containing "banner-ad")
correctly flagged via both token and ratio; normal landscape/portrait/product-screenshot/branded
launch artwork all scored 93–98 with no false warnings; the deduplication variants confirmed exact,
resized, and recompressed copies land in the same perceptual cluster as the original (distance ≤4),
while the cropped variant correctly remained a separate, unclustered image.

## 24. Bounded network validation

`scripts/phase16_m3_bounded_network_validation.py` reuses M2's exact same 20 real article URLs
(max 20 articles, max 5 images/article, max 50 total images, max 100MB total — identical caps to
M2's own bounded validation), adding M3 quality analysis and within-event deduplication on the same
already-fetched bytes with zero additional network requests. Two runs were performed (before and
after the §14 banner-signal fix):

- Run 1 (pre-fix): 35 images analyzed, 0 hard rejections, 7 warnings, 15 exact/near-duplicate
  merges, 2 transient `read_timeout` fetch errors, score range 58–98 (avg 88.5).
- Run 2 (post-fix, independent re-run — minor image-count variance is normal page-content drift
  between runs, not a code-behavior change): 31 images analyzed, 0 hard rejections, 5 warnings, 15
  duplicate merges, 0 errors, score range 58–98 (avg 89.7).

## 25. False-rejection / false-duplicate review

Per the task brief's Step 32, a bounded manual review was performed on all hard rejections, all
near-duplicate merges, and all warnings from the bounded network validation:

- **Hard rejections: 0 across both runs.** Nothing to review — no real og:image/twitter:image
  candidate from 20 real, live articles was hard-rejected, consistent with hard rejection being
  reserved for tracking pixels/favicons/extreme ratios that legitimate article hero images do not
  normally exhibit.
- **Warnings (run 1, 7 total):**
  - 3× `possible_avatar` (9to5google.com, 9to5mac.com, 9to5toys.com, all 96×96) — **correct,
    reasonable warning.** These matched an explicit avatar/author token (consistent with a shared
    publishing-platform author-thumbnail template), received only a soft penalty, and were not
    hard-rejected.
  - 2× `possible_banner` (ammoniaenergy.org 1019×438 ratio 2.33; areadenial.games 2160×791 ratio
    2.73, `wide_banner` band in both cases) — **questionable warning, root-caused and fixed.**
    Neither had a corroborating banner/ad token; the signal was firing on aspect ratio alone at the
    `wide_banner` band, which flags legitimate wide editorial hero crops. Fixed in §14 to require
    either a token match or the more pathological `extreme_wide` band (>5.0). Re-verified in run 2:
    both false warnings are gone; areadenial.games still correctly shows `possible_logo` (a genuine
    logo-token match, unaffected by this fix).
  - 1× `possible_placeholder` (arcprize.org, 1200×630) — **reasonable, conservative warning.**
    Token-based only (not the "strong" combination that would hard-reject), on an otherwise
    good-resolution, good-aspect-ratio image — exactly the ambiguous case `REVIEW` status exists
    for, not a case that should be silently accepted or rejected.
- **Near-duplicate/exact-duplicate merges (14–15 across both runs): spot-checked, 0 likely false
  duplicates found.** Every merge pairs candidates with **identical decoded width/height** within
  the same article/event (e.g. two 1200×630 pairs on abhi.now, alexklos.ca, anatolyzenkov.com,
  arcprize.org; two 1729×1729 pairs on alexwlchan.net; two 1538×1538 pairs on anthropeum.com),
  consistent with the same underlying asset being discovered twice via og:image + twitter:image (or
  + JSON-LD) metadata on the same page — correct exact/near duplicates, not distinct editorial
  images being incorrectly collapsed.
- **Errors (run 1, 2 total):** both `read_timeout` on a per-image fetch within a multi-image event
  (9to5toys.com, arcprize.org); the sibling image in the same event succeeded in both cases. Handled
  identically to M2's established `SafeFetchError` isolation — a per-image failure never aborts the
  rest of that event's candidates. No M3-specific issue; run 2 (independent network conditions) saw
  zero such errors.

No rule was tuned solely to force zero errors on this small sample — the one change made (§14) was
adopted because it matched the task brief's own explicit design guidance (multiple independent
signals before a strong wide-image penalty) and was verified not to weaken any other detection
(re-run of the full 98-test M3 suite plus the offline calibration fixtures after the change, both
unaffected in every other respect).

## 26. Performance

Per the bounded validation runs: 20 real articles, 31–35 images successfully analyzed, total
downloaded bytes ~7.4MB in run 1, all completing well within the existing per-request/per-event
timeout budget defined in `core/config.py` (`image_intelligence_total_timeout_seconds=12.0`
unchanged from M2). The additional M3 per-image cost (one grayscale 9×8 resize for the perceptual
hash, one 32×32 nearest-neighbor resize for dominant-color ratio, plus lightweight regex token
matching) is negligible relative to the network fetch time it rides alongside — no additional
network round trip is introduced.

## 27. Deployment status

`docker compose build content_worker` completed a full, reproducible image build (no `docker cp`
workaround needed this milestone — unlike M1's sandbox-egress-blocked registry pull, this build
succeeded normally). `docker compose up -d --no-deps content_worker` recreated the container from
the new image; it started cleanly and ran its normal `CONTENT_GENERATION` cycle without error.
`IMAGE_INTELLIGENCE_MODE` remains `"off"` in the deployed container's configuration (unchanged,
`.env` never edited) — the M3 code is live in the built image but dormant by the existing mode gate,
identical in spirit to M1/M2's own deployment posture.

## 28. Controlled shadow validation

`scripts/phase16_m3_controlled_shadow_validation.py` — a read-only, process-scoped script — selected
the 8 most recently collected real `NewsEvent` rows with non-null `content` (via a plain `SELECT`,
session never flushed or committed) and called `run_shadow_discovery(..., mode="shadow")` directly
in-process for each one (an explicit function argument scoped to this one-off script; the deployed
worker's own config/environment/`.env` were never touched — `IMAGE_INTELLIGENCE_MODE` stayed `off`
for the actual worker process throughout). Result: 5 of 8 events produced full M3
quality/deduplication results with sensible non-zero scores and no errors; 3 of 8 (text-only events
with no discoverable image hints) correctly produced zero candidates without any error or block.
No row was created, updated, or deleted in any table; no `EditorialTask`/`ContentDraft` was created;
no LLM/vision/paid-API provider was called (confirmed both by code inspection — `services/
image_quality.py` and `services/image_deduplication.py` import only `PIL`, `hashlib`, stdlib, and
this repo's own schemas — and by the absence of any outbound call other than the DB read and, where
`should_fetch_article` applied, the same SSRF-safe article/image fetches M2 already performs); no
Telegram message was sent (no bot/aiogram import anywhere in the M3 code path).

## 29. Zero-AI confirmation

`services/image_quality.py` and `services/image_deduplication.py` import only: `io`, `logging`,
`re`, `time`, `hashlib`, `dataclasses`, `collections.defaultdict`, `urllib.parse.urlsplit`, `PIL`
(`Image`, `ImageOps`, `UnidentifiedImageError`), and this repository's own `schemas`/`services`
modules. No OpenAI SDK, no `httpx`/network call of any kind, no other LLM/vision/ML library. This is
enforced by a dedicated test (`test_no_heavyweight_external_cv_dependency_added`) that AST-parses
the module's actual `Import`/`ImportFrom` nodes (not a source-text substring check, which was found
during development to produce a false positive against the module's own docstring). No OpenAI
endpoint or any other paid API was probed, called, or referenced anywhere in this milestone's code,
tests, or validation scripts.

## 30. Known limitations

- The `possible_logo` dimension-shape fallback (adequate + square + high dominant-color ratio) and
  the token-based heuristics generally are conservative pattern matches, not true content
  understanding — a real photographic square image with an unfortunate filename could still be
  soft-penalized; this is why these are soft `possible_*` signals feeding `REVIEW`, never hard
  rejections, and why the task brief's zero-AI constraint inherently caps precision here.
  `possible_placeholder` and `possible_banner` in particular can still occasionally warn on
  legitimate images with coincidental filename tokens — the task's own explicit tolerance ("do not
  tune rules solely to force zero errors on a tiny sample") means this residual imprecision is
  expected and by design, mitigated by routing to `REVIEW` rather than silent rejection.
- Perceptual hashing (dHash) is a coarse, global-gradient signal; a small, cropped watermark/logo
  overlay difference between two otherwise-identical photos could occasionally push distance beyond
  the auto-merge threshold (correctly erring toward `review`/non-merge, per the deliberately
  conservative threshold choice in §17) rather than merging.
- Deduplication is scoped to a single event's candidates only (never cross-event) — a genuinely
  reused stock photo across two unrelated events is out of scope for this milestone by design.
- `technical_integrity` scoring depends on `declared_width`/`declared_height` being present (from
  RSS `media:content`-style metadata); candidates without any declared dimensions receive a neutral
  (never penalized, never bonused) score component, per M2's own established convention.

## 31. M4 starting point

M3 leaves every `ImageCandidate` with a final `QualityStatus` and transparent score/signal
breakdown, but does not attempt any judgment of **relevance to the specific news event/story** —
that is explicitly out of scope here (§7 of the M3 task brief's non-goals) and is the natural next
milestone: given a pool of `accepted`/`review` candidates (post-quality, post-dedup) for one event,
rank or select the single best candidate for eventual delivery, using only deterministic/zero-AI
signals already available (discovery method confidence, quality score, position/order in the
source) unless a future milestone explicitly revisits the zero-AI constraint. `ImageIntelligenceResult`
already carries per-status counts M4 can consume directly without re-deriving them.

## 32. Rollback instructions

`IMAGE_INTELLIGENCE_MODE` stays `"off"` by default — no rollback action is required to keep M3 fully
dormant in production. To fully revert the M3 code: `git revert` the four M3 commits (or reset the
branch to `checkpoint/phase16-m2`) and rebuild `content_worker`. Because `ImageCandidate` is never
persisted, no data migration or backfill is needed in either direction — reverting is a pure code
rollback.

## M3 verdict

**PHASE 16 M3 COMPLETE — QUALITY GATE AND DEDUPLICATION READY**
