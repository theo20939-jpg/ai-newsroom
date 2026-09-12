# INSTAGRAM-VISUAL-SYSTEM-V1-1

Base commit: `00016fe` (INSTAGRAM-EXECUTION-FOUNDATION-1, must NOT be rolled back).
Worktree: `C:/Users/Theodor/ai-newsroom-ig-visual-1`, branch `feature/instagram-visual-system-v1-1`.
No Instagram credentials connected, no publication, no production deploy, no autonomous scheduling.
`instagram_publication_enabled` remains `False`.

## A. Founder rejection of the old visual output

The Founder approved the Instagram execution *architecture* delivered in
INSTAGRAM-EXECUTION-FOUNDATION-1 (content package, renderer contract, review/editorial/Art path,
shadow-safe publish adapter) but explicitly **rejected the visual design** of the three
representative renders it produced (feed post, carousel slide, Reel cover), calling it
"technical/smoke-test quality, not production visual design" and warning against mistaking
technical render success for visual approval.

Concretely, the old `_render_text_card()` path (removed in this phase - see section N) produced:
mostly empty black canvas, headline-only composition, little/no meaningful imagery, tiny secondary
copy, tiny NNJ branding, weak hierarchy, repetitive layouts across every format, carousel slides
that looked like technical title cards, and a Reel cover with no video/social-content feel.

This phase's mandate was explicit: fix the *visual* layer only, without redesigning the
execution architecture, without touching Telegram V8, and without making larger text/more red the
whole strategy.

## B. Visual-system goals

Premium, editorial, modern, visual-first, recognizable-but-restrained NINJA branding, dynamic,
clean, not template-looking, not AI-generic, not empty. The reference mental model used throughout:
premium technology editorial / product-launch campaign / modern digital magazine - never a black
quote card, a PowerPoint slide, a Telegram screenshot, or a generic social template.

For normal editorial content, a real visual subject (source photo, portrait, or a genuinely
designed graphic when no image exists) is the primary composition element; text supports it. A
plain text-only card is never the default - it exists only as an intentional fallback treatment
(section I), never the everyday look.

## C. Format families delivered

| Family | Module | Variants |
|---|---|---|
| NEWS / EDITORIAL | `services/instagram_editorial_layouts.py` | `news_full_bleed`, `news_split_panel`, `news_framed` |
| BREAKING | `services/instagram_editorial_layouts.py` | one treatment, its own (non-Telegram) urgency language |
| DATA | `services/instagram_data_layouts.py` | `data_metric_only`, `data_with_graph` |
| QUOTE | `services/instagram_quote_layouts.py` | `quote_portrait`, `quote_graphic` |
| CAROUSEL | `services/instagram_carousel_layouts.py` | 5 slide layouts (`hook`/`closing`/`fact`/`comparison`/`detail`), grammar-selected per slide |
| REEL COVER | `services/instagram_reel_layouts.py` | `reel_image`, `reel_graphic` |

Every family is genuinely new Instagram-native composition work - none is a resize or reuse of any
Telegram V8 layout, motif, or asset. No family imports `services/brand_renderer.py`,
`services/nnj_master_news_overlay.py`, `services/nnj_board_metrics.py`, `services/render_evidence.py`,
or `services/presentation_director.py` (verified structurally - section K/N).

## D. Design tokens

`services/instagram_design_tokens.py` centralizes: the palette (red as an accent only, never a
full-canvas wash), spacing/margin fractions, ~15 named typography roles (`TypeRole` dataclass:
size fraction of canvas width, weight, max lines, color) covering kicker/headline/dek/metric/quote/
slide-index/CTA text, logo sizing (standard + compact), accent-rule geometry, gradient presets
(standard + a redder BREAKING-specific top treatment), and the fallback-background parameters. No
layout module hardcodes a scattered magic constant that belongs here.

## E. Image handling

`services/instagram_image_handling.py` is the shared, Telegram-independent image layer:

- `classify_orientation()` - portrait / square / landscape, the deterministic input every
  variant-selection function reads.
- `fit_image_cover()` - fills the target frame, crops the excess, with a `focus_y` bias (slightly
  above center) so faces/subjects are not centered-and-chinned-off.
- `fit_image_contain()` - preserves the ENTIRE source image, letterboxed on a padded background -
  used wherever a source graphic (an infographic, a screenshot) must never be cropped.
- `apply_bottom_readability_gradient()` / `apply_top_readability_gradient()` - eased gradients
  (never a flat scrim) for text-over-photo legibility; BREAKING gets its own redder, stronger top
  variant as an accent, not a full overlay.
- `build_structured_fallback()` - the no-image fallback (section I).
- `draw_kicker_chip()`, `draw_corner_brackets()`, `mark_reserve_width()` / `place_brand_mark()` -
  shared chip/frame/brand-mark primitives every family reuses so the whole system shares one design
  language instead of six independent ones.
- `draw_with_alpha()` - see section K's "alpha-compositing correctness" note below; every
  low-opacity element in this system routes through it (or the metric/quote/carousel glyph layers
  that already used the same pattern) so a "faint"/"restrained" alpha value in the tokens is a real,
  verified visual property of the rendered JPEG, not a value a later `.convert("RGB")` silently
  discards.

## F. Layout variants (section 17's minimum)

- NEWS: 3 variants (`full_bleed`, `split_panel`, `framed`), selected by the source image's own
  orientation - landscape → split-panel, square → framed, portrait/none → full-bleed. Deterministic,
  never random.
- DATA: 2 variants, selected by whether a real `series` of ≥2 points was supplied.
- QUOTE: 2 variants, selected by whether a real portrait image was supplied.
- CAROUSEL: 5 slide layouts, selected by each slide's own real `role` string (see section G).
- REEL COVER: 2 variants, selected by whether a real source image was supplied.

All selection functions are pure, deterministic, and unit-tested (`tests/test_instagram_visual_
system_v1_1.py`) - none uses `random`, a hash-based coin-flip, or any uncontrolled input.

## G. Carousel grammar

`services/instagram_carousel_layouts.py::select_slide_layout()` maps each slide's real
`InstagramCarouselSlideCreative.role` (a free-text field - not every carousel uses every role) to
one of 5 layouts sharing one design system but visually distinct:

- **slide 0, or `role == "hook"`** → `carousel_hook` - the strongest visual moment: a real hero
  image (cover-cropped, bottom-gradient, large headline) when supplied at render time, or an
  oversized "1" watermark when not.
- **`role in {"cta", "takeaway"}`** → `carousel_closing` - a distinct soft-red-wash treatment,
  never the hook's or a middle slide's palette - conclusion/implication, an accent rule, optional CTA
  line.
- **`role == "data"`** → `carousel_fact` - a callout treatment (an oversized `#` glyph, centered
  statement) for a single striking figure, distinct from the plain detail card.
- **`role == "comparison"` AND the slide's own copy contains a real "X vs Y" split** →
  `carousel_comparison` - a genuine two-panel split with a VS badge. If the copy does NOT actually
  contain two real sides, this deliberately falls back to `carousel_detail` rather than fabricating
  a comparison structure the content doesn't have.
- **everything else** (`context`/`problem`/`explanation`/any unrecognized role) → `carousel_detail`
  - a human-readable role label (e.g. "THE PROBLEM", "HOW IT WORKS"), a numbered progress readout,
  a body statement, and a large ghosted slide-index numeral filling what would otherwise be the
  plainest layout in the deck with real content (the slide's own position in the sequence).

Every slide carries a real "NN / MM" progress readout (an honest position signal, not decoration)
and the shared brand mark. Slide count stays bounded by the existing `_MAX_CAROUSEL_SLIDES = 10`
enforced in `services/instagram_platform_renderer.py::render_instagram_carousel()`.

## H. Reel cover grammar

`services/instagram_reel_layouts.py` treats a Reel cover as viewed in three different crops: the
full 9:16 player, the Reels-tab grid (a centered, narrower crop of the cover), and the profile grid
(the same behavior, tighter). `ProfileSpec.safe_top_frac`/`safe_bottom_frac` only account for the
Reels player's OWN chrome (progress bar, caption/action column); they say nothing about grid
cropping. `_grid_safe_band()` computes a second, narrower "survives-the-grid-crop" band, and both
variants place the hook text (and only the hook text; the mark stays in its own reserved corner)
inside that band - verified by a dedicated Art-validator check (section J) and a direct unit test.
The no-image variant adds a large, low-alpha play-button ring+triangle - a genuine "this is video"
cue instead of a static card indistinguishable from a feed post.

## I. Fallback system (no image supplied)

`build_structured_fallback()` never returns a flat black rectangle: a faint technical grid across
the whole frame plus 0-3 deterministically-seeded raised geometry blocks (seeded from the package's
own identity - the same package always produces the same fallback; two different packages produce
visibly different arrangements). DATA and the no-portrait QUOTE pass `block_count=0` (their own
hero metric/chart or oversized quotation glyph already carries the visual weight; the generic
NEWS/BREAKING panel blocks would just read as unrelated clutter there) and add their own bespoke
richness instead - a low-alpha echoed metric-number watermark and instrument-dial ring for DATA, an
oversized ghosted quotation mark for the graphic QUOTE variant, an oversized index numeral for a
plain CAROUSEL detail slide. The fallback is a genuine last resort, never the dominant look of a
normal post - every family is image-forward by construction whenever a real image is supplied.

## J. Art / evidence updates

`InstagramRenderEvidence.source_image_treatment`'s vocabulary is extended (a `str` field, not a
narrowed enum - additive, no schema break) to include the values
`services/instagram_image_handling.py::SourceImageTreatment` actually produces
(`cover_cropped`, `contain_preserved`) alongside the pre-existing `none`. Every `LayoutResult` from
every new module is converted to `InstagramRenderEvidence` through one function,
`instagram_platform_renderer.py::_result_from_layout()`, so the evidence contract every downstream
layer (review package, editorial gate, Art validator, publish adapter) already reads is completely
unchanged in shape.

`services/instagram_art_validator.py` keeps every pre-existing check (canvas/profile match,
brand-mark count exactly 1, headline-clip = blocking vs secondary-clip = warning, empty content,
package linkage, carousel slide-index/count consistency) and adds only truthful, evidence-derived
checks:

- **source-image integrity**: an `source_image_treatment` outside the real vocabulary is now
  BLOCKING (the evidence would otherwise be lying about what happened to the pixels); a package
  that recorded a real `source_image_ref` but whose render shows `none` is a WARNING (the caller
  likely forgot to pass the real bytes at render time).
- **DATA number integrity**: evidence claiming the `data_with_graph` layout without the
  `series_points ≥ 2` count to back it up is BLOCKING - the renderer itself never produces this
  combination (`select_data_variant()` only returns the graph variant for a real ≥2-point series),
  so this check exists to catch any future evidence-tampering or refactor bug, not a normal-path
  failure.
- **Reel-cover critical-content placement**: any `hook`-kind text region falling entirely outside
  the render's own recorded `grid_safe_band` is BLOCKING.
- **carousel visual-grammar diversity**: a WARNING (not blocking - a short, all-one-role deck can
  legitimately share one non-hook layout) when a carousel of ≥3 slides shows every non-hook slide
  using the identical `layout_variant`.

No subjective "aesthetic quality" gate was added - every new check reads a truthful, already-
computed evidence field, never a vision-model opinion.

## K. Tests

`tests/test_instagram_visual_system_v1_1.py` (49 new tests): image composition (cover-crop exact
target + treatment, contain-fit never destroys the source, focus_y bias), no-image fallback
(never a flat single-color fill, deterministic per identity, block_count=0 still keeps the grid),
layout selection for all 6 families (orientation/series/image-presence/role-driven, including the
carousel comparison's "only with a real vs-split" guard), the exactly-one-visible-brand-mark
invariant across 9 representative layout calls, text-overflow clipping signal (reasonable headline
never clips; an extreme one clips with a signal, never silent overflow), mark-reserve-width safe-
zone math, Reel grid-safe-band placement (unit + end-to-end via the Art validator), full renderer
wiring (`render_instagram_feed_image` defaulting to NEWS / honoring `presentation_family=
"breaking"` / accepting a real `source_image`; the new `render_instagram_single_data`/
`render_instagram_single_quote` entrypoints requiring SINGLE format and never fabricating a graph
without a real series; `render_instagram_carousel` producing a genuinely varied grammar with the
hero image applying only to the hook slide; `render_instagram_reel_cover` honoring grid-safe
placement end-to-end), the two new Art-validator checks (DATA graph integrity, carousel diversity
warning, source-image-ref consistency warning), the two new additive `InstagramContentPackage`
fields defaulting to `None`/serializing correctly, and a parametrized Telegram-V8 import-boundary
proof (AST-based, matching the Foundation phase's own pattern) for every one of the 8 new/changed
visual modules.

**A real correctness bug this test suite caught mid-phase** (disclosed, not hidden): PIL's
`ImageDraw` does not alpha-blend a fill/outline color against an existing RGBA canvas - it
overwrites the RGB outright and only stores the given alpha, which a later `.convert("RGB")`
silently drops. Every "faint"/"restrained" alpha value in the original draft of this system (the
fallback grid/blocks, corner brackets, the DATA dial) was therefore dead code that happened to
render at full strength - invisible in review only because the chosen colors were already close to
the background. Fixed via a shared `draw_with_alpha()` helper (draw on a transparent layer, then
`Image.alpha_composite`) and recalibrated token values; a companion bug in `mark_reserve_width()`
(it reserved the mark's own width but forgot the mark's own right-margin) was caught the same way -
a one-line dek/context/quote-role row could land close enough to the brand mark to read as a
collision even though the "reserve" math looked satisfied. Both are fixed and every affected render
was regenerated and re-viewed.

**Regression**: the existing 58 Foundation-phase tests
(`tests/test_instagram_platform_renderer.py`, `test_instagram_content_package.py`,
`test_instagram_art_validator.py`, and friends) all pass unchanged against the new renderer -
`render_instagram_feed_image`/`_carousel`/`_reel_cover` keep their original call signature
(package-only) and only gained optional new keyword arguments. A scoped sweep across every
Instagram/Growth/Social-Integration/Campaign/Director/Art/Presentation/Control-Plane test file
(80 files) => **701-702 passed** across repeated runs; the only failures reproduce on unrelated,
pre-existing files this phase never touched (`test_director_console_service.py::
test_no_campaign_no_story_notes_are_honest` and `test_presentation_director_mode_contract.py::
test_enforce_gate_actually_assigns_every_mutating_target_at_least_once`, both already documented
as pre-existing dev-DB/stale-contract gaps in the Foundation-phase report) plus two
`test_director_editorial_gate_pre_generation.py` cases that failed only inside the full 80-file
sweep and passed cleanly (7/7) when re-run in isolation - a pre-existing test-isolation/shared-dev-
DB-state sensitivity to run order, not a regression from any file this phase touched (verified: zero
diff between this branch and `00016fe` for `services/workflow_service.py` and every director-
editorial-gate file). **`NEW_FAILURES = 0`.**

`ruff check` + `mypy --ignore-missing-imports` are clean (`0` errors/warnings) on all 11
new/changed Python files.

## L. Contact sheet

`artifacts/instagram_visual_system_v1_1/00_CONTACT_SHEET.jpg` - one board showing all 8 required
formats together (NEWS-gadget/product, NEWS-AI/software, BREAKING, DATA-with-graph, DATA-metric-
only, QUOTE-with-portrait, 4 representative CAROUSEL slides, REEL COVER) for brand consistency /
feed diversity / hierarchy / Instagram suitability / visual richness review in one place.

## M. Individual review renders

`artifacts/instagram_visual_system_v1_1/` also carries every full-resolution individual render
(`01_NEWS_GADGET.jpg` through `08_REEL_COVER.jpg`, plus all 6 carousel slides
`07_CAROUSEL_00_hook.jpg`…`07_CAROUSEL_05_cta.jpg`) produced by
`scripts/_instagram_visual_system_v1_1_canary.py`, using only real, already-approved local image
fixtures (`assets/brand/newsroom_visuals/v2_1_bakeoff_sources/case{1,2,3}_*.jpg`,
`tests/fixtures/portrait_public_figure.jpg`) and Cyrillic/Russian NINJA PULSE copy throughout - no
English placeholder headline anywhere in the canary. The QUOTE canary attributes its quote to "Тим
Кук / CEO, Apple" because the pictured fixture IS that real, recognizable person (the same
attribution discipline the prior FOUNDER-VISUAL-POLISH-2 phase established for this exact fixture) -
never a fabricated name paired with a real identifiable face.

## N. Architecture-unchanged proof

- `git diff --stat 00016fe -- services/brand_renderer.py services/nnj_master_news_overlay.py
  services/nnj_board_metrics.py services/render_evidence.py services/presentation_director.py
  assets/brand/fonts/` => empty (zero bytes changed) - **`TELEGRAM_V8_RUNTIME_CHANGED = false`**.
- Every new visual module (`instagram_design_tokens.py`, `instagram_image_handling.py`,
  `instagram_text_fit.py`, `instagram_editorial_layouts.py`, `instagram_data_layouts.py`,
  `instagram_quote_layouts.py`, `instagram_carousel_layouts.py`, `instagram_reel_layouts.py`) is
  proven, via a parametrized AST-import-boundary test, to contain zero `import`/`from ... import`
  reference to any frozen Telegram V8 module.
- `InstagramContentPackage`, `InstagramReviewPackage`, `InstagramPublicationRequest`, the publisher
  adapter, publication safety gates, the shadow-publish flow, and editorial-outcome semantics are
  byte-for-byte untouched except for the two additive fields disclosed in section D of the phase
  spec (`presentation_family: str | None = None`, `source_image_ref: str | None = None`) - both
  optional, both defaulting to `None`, both already covered by a dedicated backward-compatibility
  test. `to_dict()` gained the two corresponding keys; every other field, every validation path, and
  `build_instagram_content_package()`'s existing behavior for every caller that doesn't pass the two
  new optional keywords is unchanged.
- `services/instagram_platform_renderer.py`'s three original public entrypoints
  (`render_instagram_feed_image`, `render_instagram_carousel`, `render_instagram_reel_cover`) keep
  their original call signature (a package is always sufficient) and only gained new *optional*
  keyword-only parameters (`source_image=None` / `hero_image=None`) for real media - no existing
  caller's code needs to change. Two new entrypoints (`render_instagram_single_data`,
  `render_instagram_single_quote`) were added rather than overloading the SINGLE-feed default with
  guessed/parsed structured data the existing creative schema does not actually carry (see the
  disclosed scope note below).
- `instagram_publication_enabled` was not touched; no Instagram credentials exist in this worktree;
  no network write occurred at any point in this phase.

### Disclosed scope note

`InstagramSingleCreative` (the real Creative Director schema for a SINGLE post) carries no
structured metric/series or speaker/quote field. Rather than parse a "metric" or a "quote" out of
free-text `on_image_copy`/`caption_direction` (which would risk exactly the kind of fabrication
section 9's "never fabricate chart points" forbids), `render_instagram_feed_image()` only
auto-selects between NEWS (default) and BREAKING (`presentation_family="breaking"`) - both of which
map cleanly onto the existing headline/dek/cta fields. DATA and QUOTE are fully built, tested, and
demonstrated via the canary (section M), and reachable at the package level today through the two
new dedicated entrypoints for a caller that already has real structured data (e.g. a future
Data-Insight opportunity type) - not yet auto-selected from a generic SINGLE creative, which would
require a real upstream schema change out of this phase's scope.

## Verdict

**`INSTAGRAM_VISUAL_SYSTEM_V1_READY_FOR_FOUNDER_REVIEW`**

Technical implementation complete: all 6 visual families built, wired, tested (49 new + 58
preserved Foundation tests, `NEW_FAILURES = 0`, `NEW_STATIC_ERRORS = 0`), and demonstrated via a
real 8-format canary + contact sheet using only real local imagery and Russian NINJA PULSE copy.
This is **not** Founder-approved design - per section 25, stopping here for visual review. No
Phase 2 work, no Instagram credentials, no publish.
