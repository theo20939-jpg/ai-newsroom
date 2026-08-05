# Phase 18 M6 — Meme Rendering / Text Overlay: Implementation Report

Status: complete. Fully deterministic, local, zero-network, zero-LLM. No settings/mode flag is
needed for this milestone — rendering is pure post-processing of bytes M5 already produced (or
any base image bytes), so there is no "off" state to gate; the function simply is or isn't called
by an orchestrator (none exists yet, same deferral as M2–M5).

## 1. What was built

| File | Purpose |
|---|---|
| `schemas/meme_render.py` | `MemeRenderResult`, `MemeRenderStatus` |
| `services/meme_render.py` | `render_meme()` — text wrap/fit, contrast selection, safe-zone drawing, storage |
| `tests/test_phase18_m6_meme_render.py` | 13 tests |

## 2. How it satisfies each brief requirement

- **Overlays text** — `MemeCopy.top_text`/`bottom_text` are drawn centered within their band,
  word-wrapped to fit.
- **Safe zones, never covers the key object** — only the top and bottom ~18%-height bands are
  ever drawn into; the center ~64% is never touched. This is a *structural* guarantee (nothing in
  the center band is ever passed to `ImageDraw`), not a per-image heuristic — verified directly by
  `test_center_safe_zone_is_never_drawn_into`, which diffs the exact center-crop pixels of the
  base image against the rendered one and asserts byte-for-byte equality. This relies on the same
  "subject occupies the visual center" convention `services.meme_image_generation.
  build_image_prompt()` already assumes when instructing the (mock, today) generator — disclosed,
  not hidden, as a real limitation once a genuinely off-center real-model composition exists (§5).
- **Checks contrast** — `_choose_text_colors()` computes the real WCAG relative luminance of the
  band's own average background color, tries both (white-fill/black-stroke) and (black-fill/
  white-stroke), and picks whichever produces the higher measured ratio; `MemeRenderResult.
  top_text_contrast_ratio`/`bottom_text_contrast_ratio` report the actual number, and
  `contrast_passed` is `False` if either present band falls below `_MIN_CONTRAST_RATIO = 3.0`
  (WCAG's own "large text" minimum) — a real, computed check, not an assumption. A stroke outline
  is always drawn in addition (belt-and-braces: guarantees legibility even in the rare case both
  fill choices score similarly against a busy background).
- **Saves the final asset** — reuses `integrations.storage.image_storage.ImageStorage` (the exact
  same abstraction M5 already reuses from Phase 16) — content-addressed, idempotent
  (`test_deterministic_same_inputs_produce_same_output` proves re-rendering identical inputs
  yields the identical stored key, never a duplicate).
- **Creates an editor-preview version** — interpreted as: the fully rendered (text-overlaid)
  asset itself *is* the editor-facing preview (the brief's own framing — "особенно важно, если
  image generation отдаёт картинку без финального текста" — describes exactly this module's job:
  M5 deliberately produces text-free images, §5 of the M5 report; M6's output is the first and
  only version a human ever needs to see). No separate, additional watermarked/downscaled variant
  was built — a second asset variant was considered and rejected as scope not requested by the
  brief's own wording, which describes one outcome ("создаёт editor-preview version"), not two.

## 3. Real visual verification (not just automated assertions)

A rendered sample (mock base image + `MemeCopy(top_text="AI WON'T TAKE YOUR JOB",
bottom_text="SAYS GUY WHOSE JOB IS LITERALLY AI")`) was generated and visually inspected during
development: white text with a black outline, correctly centered in the top and bottom bands,
the center placeholder circle (standing in for a real generated subject) completely untouched.
This is a real image, not merely passing assertions — it was rendered, viewed, and then discarded
(no output committed to the repository; nothing under version control changed as a result of this
manual check).

## 4. Testing

13/13 tests pass: WCAG luminance math (white=1.0, black=0.0, black-on-white ratio=21.0,
symmetry); word-wrap keeps short text on one line and correctly splits long text with every
wrapped line verified to actually fit the declared max width; end-to-end render produces a valid
1024×1024 PNG and stores it; both band contrast ratios are reported and `contrast_passed` is
`True` for a normal case; a `None` `bottom_text` correctly leaves `bottom_text_contrast_ratio`
`None` (never a fabricated value); the center safe zone is provably untouched (pixel-identical
crop before/after); the truncation mechanism is proven directly (`_fit_text_to_band` with an
artificially tiny `max_height`) and end-to-end (`render_meme` with `_BAND_HEIGHT_FRACTION`
monkeypatched down) — both confirm text that cannot fit even the smallest font size is truncated
and reported via `safe_zone_violations`, never silently drawn over the safe zone; rendering is
deterministic (identical inputs → identical `sha256`/`storage_key`); malformed base-image bytes
return `FAILED` with an `error_code` rather than raising.

Regression: full Phase 18 suite — **95/95 pass** across all six milestones. `python -m pytest
--collect-only -q` — **2238 tests collected** (2225 + 13 new), 0 collection errors.

## 5. Known limitations (disclosed)

- **No bundled display font** — uses Pillow's built-in scalable default font, not a licensed
  display/Impact-style font (none is bundled in this repository, and adding a font asset without
  clearing licensing was out of scope for this milestone). The rendered text is legible and
  correctly positioned/contrasted, but not styled like a "classic meme" font. A future milestone
  can swap in a bundled `.ttf` with no change to the wrap/fit/contrast logic — `_load_font()` is
  the single, isolated seam that would change.
- **Safe-zone/center-object avoidance is convention-based, not vision-based** — this module has
  no object-detection capability; it assumes (correctly, for both `MockImageAdapter`'s placeholder
  and `build_image_prompt()`'s own prompt instructions) that the generated subject sits centered.
  A future real image-generation provider that ignores composition guidance could produce a
  subject positioned in the top/bottom bands, which this renderer would then draw over — a real,
  disclosed risk to revisit once a real provider adapter exists (M5 report §6/§7).
- Minor: Pillow 12.3 flags `Image.getdata()` as deprecated (removal targeted 2027) — functionally
  harmless today, noted for a future cleanup pass rather than fixed now (the suggested
  replacement, `get_flattened_data`, is not guaranteed present across this project's declared
  `Pillow>=11.0` floor).

## 6. Next milestone

M7 (Meme Quality Gate) — combines M1 (opportunity), M3 (safety/originality), and M6's own
contrast/safe-zone signals into one pre-preview decision (READY_FOR_EDITOR / REVIEW /
REGENERATE_CONCEPT / REGENERATE_IMAGE / REJECT), with a hard-bounded regenerate loop.
