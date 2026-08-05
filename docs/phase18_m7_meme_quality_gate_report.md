# Phase 18 M7 — Meme Quality Gate: Implementation Report

Status: complete. Zero LLM/network calls — pure combination of M1/M3/M5/M6's already-computed
results plus two new, narrow, deterministic M7-local checks.

## 1. What was built

| File | Purpose |
|---|---|
| `schemas/meme_quality.py` | `MemeQualityDecision`, `MemeQualityChecks`, `MemeQualityAssessment` |
| `services/meme_quality.py` | `assess_meme_quality()`, `apply_regeneration_bounds()` |
| `tests/test_phase18_m7_meme_quality_gate.py` | 18 tests |

## 2. The decision tree, and why it's ordered this way

Five outcomes (`READY_FOR_EDITOR` / `REVIEW` / `REGENERATE_CONCEPT` / `REGENERATE_IMAGE` /
`REJECT`), evaluated worst-first — a later, milder check is never reached once an earlier, harder
one has already decided:

1. **M3 safety/originality `BLOCK`, or M1 `SENSITIVE_BLOCK`** → unconditional `REJECT`. No
   combination of good render/copy/originality scores overrides it (`test_reject_overrides_even_
   a_perfect_render` proves this directly).
2. **Image generation or render failure, or a failed contrast/safe-zone check** → `REGENERATE_
   IMAGE`. A rendering-level problem is fixable with a new image; nothing about the concept or
   copy is implicated.
3. **M3 originality `REVIEW`** → `REGENERATE_CONCEPT`, not `REVIEW`. This required tracing through
   *what* M3's originality check actually evaluates: it runs against `MemeConcept.punchline`
   (a near-duplicate-of-headline concept), not the final `MemeCopy` — rewriting the copy alone
   cannot fix a fundamentally unoriginal concept, so the gate correctly recommends regenerating
   the concept, not the copy.
4. **M3 safety `REVIEW`, M1 opportunity `REVIEW`, or a failed M7-local check** (factual alignment/
   punchline clarity/brand fit) → `REVIEW`. Never silently auto-approved.
5. **Everything clean** → `READY_FOR_EDITOR`.

## 3. The two new M7-local checks

- **Factual alignment (coarse)**: every number appearing in the on-image copy text (`top_text`/
  `bottom_text`/`punchline_short`) must already appear somewhere in the concept's own grounding
  text (`premise`/`setup`/`punchline`/`source_fact_links`) — catches a copywriting-stage
  fabricated statistic (e.g. inventing "$500 million" that the concept never mentioned). This is
  disclosed as coarse (module docstring) — it cannot catch a subtler factual drift that doesn't
  involve a number, matching this phase's general pattern of narrow, testable, versioned
  heuristics rather than claiming a general fact-checker.
- **Brand fit (coarse)**: a short, disclosed-incomplete blocklist of obviously crude/mean-spirited
  phrases (mirrors `services/meme_safety.py`'s own known-meme-template list precedent) — not a
  general toxicity classifier.
- **Punchline clarity**: `punchline_short` must be at least 3 words — a minimal, real floor
  against a degenerate one/two-word "punchline" that isn't actually a punchline.
- **Readability/originality/meme_safety/visual_quality/mobile_friendliness** in
  `MemeQualityChecks` are direct, honest readouts of M3/M5/M6's own already-computed results —
  never recomputed independently, so they can never silently disagree with the milestone that
  actually owns that judgment.

## 4. Bounded regeneration — enforced, not just documented

`apply_regeneration_bounds()` is a required second call, not an optional safety note:
`MAX_CONCEPT_REGENERATIONS = 1` and `MAX_IMAGE_REGENERATIONS = 1` are real constants a
`REGENERATE_CONCEPT`/`REGENERATE_IMAGE` recommendation is checked against, downgrading to
`REJECT` once the caller-supplied attempt count (from `MemeCandidate.concept_regeneration_count`/
`image_regeneration_count`, reserved since M2) already meets the bound. `assess_meme_quality()`
itself contains no loop of any kind — it computes one recommendation per call; bounding a
*sequence* of calls is `apply_regeneration_bounds()`'s entire job, tested directly in both
directions (regeneration allowed under the bound, downgraded to REJECT at/over the bound) plus a
no-op check for the already-terminal `READY_FOR_EDITOR` case.

## 5. Testing

18/18 tests pass: the full precedence tree (REJECT overriding a perfect render; SENSITIVE_BLOCK
→ REJECT; image/render failure, contrast failure, and safe-zone violations all independently
triggering REGENERATE_IMAGE; originality REVIEW specifically triggering REGENERATE_CONCEPT, not
generic REVIEW; safety REVIEW and opportunity REVIEW both triggering plain REVIEW, not
regeneration); the two local checks (an unattributed number in copy fails factual alignment and
triggers REVIEW; the same number present in the concept's own grounding passes; a too-short
punchline fails clarity; crude language fails brand fit) — all independently triggerable and
independently observable via `MemeQualityChecks`; and bounded regeneration in both directions
(allowed under the bound, downgraded to REJECT at the bound, no-op for an already-terminal
decision).

Regression: full Phase 18 suite — **113/113 pass** across all seven milestones together.
`python -m pytest --collect-only -q` — **2256 tests collected** (2238 + 18 new), 0 collection
errors.

## 6. Risks / limitations carried forward

- Factual-alignment and brand-fit checks are coarse, keyword/number-based heuristics — same
  disclosed-limitation pattern as every other zero-LLM classifier in this phase (M1's irony
  detection, M3's sensitivity/template lexicons).
- The gate has no visibility into whether the *image itself* (as opposed to the render's
  text/contrast) is actually good — `visual_quality` currently only checks that generation/
  rendering *succeeded*, not that the resulting picture is aesthetically coherent (M5's mock
  provider makes this question moot today; it becomes real once a genuine image-generation
  provider exists).
- `opportunity` is an optional parameter — a call site that never has an M1 assessment available
  (e.g. a MEME_GENERATION task spawned by a path that skipped the CONTENT_GENERATION quality step
  entirely) still gets a full quality assessment, just without that one signal. This is
  intentional (M1's shadow hook is itself optional/off by default), not an oversight.

## 7. Next milestone

M8 (Telegram Editorial Preview) — the first milestone touching Telegram at all. Ships with a
`meme_telegram_preview_mode="off"` default and the same dry-run-before-live-send discipline
`services/telegram_notifier.py` already established; no live Telegram send without separate,
explicit human authorization.
