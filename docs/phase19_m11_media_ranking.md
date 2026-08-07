# Phase 19 M11 — Media Ranking + Story-Aware Reuse Prevention

## 1. Scope decision: no new persistence table

`services/media_ranking.py::rank_media_candidates()` is a pure, 100%-deterministic computation
over already-available signals — given the same inputs, it always produces the same output, so
nothing is lost by recomputing it on demand. Unlike M7/M8/M10 (which persist genuinely
non-reproducible data — an LLM-adjacent scaffold, a timeline snapshot, a discovered URL), a
ranking run itself needs no durable table in this milestone; a future caller (M12's delivery
selection, or a manual review script) decides whether/how to log a specific run's output. This
keeps M11 a narrow extension rather than a new hot-path write path.

## 2. `MediaRankingResult` (`schemas/media_ranking.py`)

All fields from the approved spec: `media_item_id`, `media_type`, `relevance_score`,
`source_priority`, `quality_score`, `novelty_score`, `story_reuse_penalty`, `branding_risk`,
`recommended_role`, `recommended_order`, `explanation`, `eligible_for_delivery`.

`RecommendedRole`: `HERO` / `SUPPORTING` / `TECHNICAL_DETAIL` / `CHART_OR_DIAGRAM` /
`DEMO_VIDEO` / `CONTEXT_VIDEO` / `REJECT`. `TECHNICAL_DETAIL`/`CHART_OR_DIAGRAM` are declared but
never assigned by this milestone's own deterministic logic — no signal exists yet (in
`services/image_quality.py` or elsewhere) to distinguish a chart/diagram/technical screenshot
from ordinary editorial photography; assigning either role would be a fabricated distinction.
Documented here rather than silently omitted from the enum, since a future milestone may add that
signal.

## 3. Deterministic scoring (`rank_media_candidates`)

Composite score = `quality_score + source_priority + relevance_score(neutral 50 if absent) -
story_reuse_penalty(40 if reused) - duplicate_within_event_penalty(25) - branding_risk`.
`eligible_for_delivery` requires: not a rejected video, not a story-reuse match, and
`quality_score >= 30`. Role assignment: any ineligible candidate → `REJECT`; a valid video → 
`DEMO_VIDEO` (16:9-ish aspect) or `CONTEXT_VIDEO` (otherwise); an eligible image → `HERO` only if
high quality, editorial-landscape aspect, **and** low branding risk, else `SUPPORTING` — branding
risk alone never disqualifies delivery, only demotes from `HERO`.

Pure, no I/O — `tests/test_media_ranking.py` (20 tests) covers ranking order, tie-breaking,
eligibility, role assignment, and the branding-risk cap.

## 4. Story-aware reuse prevention

The first cross-event duplicate-awareness in this codebase — `services/image_deduplication.py`
(Phase 16 M3) is explicitly scoped to one event only (its own module docstring). M11 extends this
without modifying that module: `find_story_reused_image_signatures()` queries every *other* event
already linked (via `NewsEventStoryLink`) to the same `Story`, returning their `sha256`/
`perceptual_hash` values; `is_perceptually_reused()` compares a new candidate against these using
`services/image_quality.py::hamming_distance()` and the exact same calibrated threshold
`image_deduplication.py` already uses (`4`) — never a new, divergent threshold for the same
underlying question. `find_story_reused_video_urls()` does the analogous exact-URL check against
`content_draft_media_items` (M10) — no perceptual video hashing exists in this codebase, and
building one is explicitly out of scope.

Both queries are bounded to the one story's own linked events (never a cross-story or table-wide
scan) — `tests/test_media_ranking_story_reuse.py` (4 tests, real migrated-database integration,
runtime table-existence skip) proves correct inclusion/exclusion.

## 5. M3 isolation preserved

Per the overnight authorization's own explicit requirement: since Editorial Planning (M3) is
shadow/comparison-only and never influences live Copywriting, live production media ranking must
not become dependent on shadow Editorial Plan output either. `MediaRankingInput`/
`rank_media_candidates()` never reference `media_role_needed` or any other Editorial Plan field at
all — this isolation is structural (nothing to import, nothing to wire), not merely a convention
kept by discipline.

## 6. Validation performed

- `tests/test_media_ranking.py` (20 tests): pure calculator, no I/O.
- `tests/test_media_ranking_story_reuse.py` (4 tests): real, migrated-database proof of the
  cross-event queries; skips cleanly against the real, unmigrated dev DB.
- No new migration in this milestone (no new table) — validated against the same disposable DB
  chain already carrying M7–M10's migrations.
- Ruff/Mypy clean.

## 7. What this milestone does NOT do

- Does not add a new settings flag or persistence table.
- Does not assign `TECHNICAL_DETAIL`/`CHART_OR_DIAGRAM` (no signal exists for either yet).
- Does not read or depend on shadow Editorial Plan (`media_role_needed`) output.
- Does not wire ranking results into live delivery — that is M12's own scope.
