# Phase 19 M9 — Deterministic Media-Quality Pre-Filter

## 1. Scope and explicit limitation

**M9 = a cheap, deterministic, obvious-case filter. M13 = optional future vision refinement.**

M9 extends `services/image_quality.py` (Phase 16 M3) with three new deterministic signals, using
the exact same combination-of-evidence, `possible_*`-only convention already established in that
module. It does **not** claim to catch every embedded logo, watermark, or UI chrome — only the
cheap, obvious cases that URL/alt-text tokens or gross pixel-uniformity statistics can detect
without a vision model. A determined/subtle watermark, a cropped-in logo, or a screenshot with a
photorealistic background will not be caught here; that is exactly the gap Phase 19 M13's
(optional, future) vision review foundation exists to eventually narrow — M9 makes no attempt to
solve that problem now.

## 2. The three new signals

All three are soft, `possible_*` signals only — folded into the same `QualitySignals`/
`quality_warnings`/`quality_penalties` machinery every existing Phase 16 M3 signal already uses.
**None of them are ever added to `hard_rejection_reasons`** — ambiguous evidence always routes to
REVIEW (a lower `quality_score`, a warning flag), never an automatic hard rejection, per this
milestone's own explicit requirement.

1. **`possible_watermark`** — URL/filename/alt-text token evidence only (`watermark`,
   `watermarked`, `wm-overlay`, plus Russian equivalents), same word-boundary-aware pattern as
   every existing token set (`_LOGO_TOKENS` etc.). Deliberately no pixel-based watermark signal —
   a real overlay could be anywhere in the frame, any color, any opacity; no cheap deterministic
   statistic reliably detects one without false-flagging ordinary editorial photography.
2. **`possible_tv_lower_third`** — a conservative heuristic: a 16:9-ish frame (aspect ratio
   1.7–1.85) whose bottom ~22% band has markedly lower grayscale variance than the frame's middle
   band (the shape of a solid/gradient text bar overlaid on broadcast footage). Ambiguous by
   construction (a legitimate photo with a plain sky/wall crop at the bottom scores identically) —
   always a soft warning.
3. **`possible_branded_screenshot`** — the fraction of near-flat rows on a downsampled 64×64
   grayscale canvas (UI chrome — toolbars, scrollbars, flat panels — produces far more flat rows
   than typical photography). A lower bar applies when corroborated by a `screenshot`-family URL/
   alt-text token; a higher bar applies to the pixel signal alone.

## 3. No new setting

These signals ride the existing `image_intelligence_mode` gate — `analyze_candidate()` (the sole
entry point they're wired into) is only ever called from `services/image_intelligence.py`'s
already-gated pipeline (confirmed: the only other callers are offline calibration/validation
scripts, never a production path). Adding a REVIEW-capable soft signal to an already-shadow-gated
analysis function does not change what gets rejected/accepted under current default settings —
only what gets *logged* as a warning for an image that was already going to be scored.

## 4. Validation performed

- `tests/test_image_quality_prefilter.py`: deterministic, in-memory Pillow fixtures distinguish a
  textured (photo-like) image from a flat-banded (TV-lower-third-shaped) or flat-striped
  (UI-chrome-shaped) one for each new signal, and explicitly proves ambiguous/multi-signal cases
  never reach `hard_rejection_reasons`.
- Full pre-existing `tests/test_image_quality.py` suite (48 tests) still passes unmodified.
- Ruff/Mypy clean.

## 5. What this milestone does NOT do

- Does not add a new settings flag.
- Does not hard-reject any image on the basis of these three signals.
- Does not attempt real watermark/logo detection via pixel analysis — token evidence only.
- Does not touch M13's (future, optional) vision-based refinement.
