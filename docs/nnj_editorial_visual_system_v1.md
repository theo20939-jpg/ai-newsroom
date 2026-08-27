# NNJ Editorial Visual System v1

Status: **Phase V1 (prototype-driven reconciliation) implemented in `services/brand_renderer.py`,
uncommitted, local-preview-only.** `presentation_director_mode` remains `"off"` - nothing in this
document or the current diff activates production visual delivery, calls an LLM/image-generation
API, or sends Telegram. See §2 for what changed and why, and the Phase V1 report for local preview
paths/results.

**CANONICAL DESIGN REFERENCE**: `assets/brand/newsroom_visuals/v1/references/
nnj_editorial_visual_system_master_prototype.png` - the approved Telegram-channel prototype
(desktop + mobile, all five presentation types). It was missing from the original asset audit and
was added in a corrective pass; see the corrective reference audit report for the delta. This
prototype outranks every generated overlay experiment when judging visual style (hierarchy:
prototype > canonical NNJ logos > approved overlays > secondary references).

**Companion document**: `docs/nnj_source_faithful_editorial_visual_recomposition_v1.md` ("V2")
defines a separate, not-yet-implemented capability that would sit *before* this document's
deterministic brand layer - recomposing the base image itself while this document's own palette/
geometry/prototype rules continue to govern how the NNJ brand mark is applied on top. V1 remains
fully responsible for the brand layer either way; V2 does not change anything documented here.

## 1. What this is

A minimalist visual accent language for NINJA PULSE editorial media: the source/news image stays
dominant, with a thin bottom-edge line (optionally carrying a small red NNJ pulse/ECG motif) and
restrained NNJ branding as the signature device. Family variants exist for NEWS / BREAKING /
QUOTE / DATA / RECAP, all visibly part of one family. The overlay is a compositional accent, never
a rigid frame arbitrary images are forced into.

## 2. Reconciliation with the existing NINJA PULSE Visual System (read this first)

**A complete, already-built visual system covering almost this exact scope already exists in this
repository**: `services/presentation_director.py` (deterministic NEWS/BREAKING/DATA/QUOTE
classification, zero new LLM call, reuses existing Copywriting v8-family fields) +
`services/brand_renderer.py` (Pillow-only compositor: official logo paste, hand-drawn pulse line,
per-type card rendering, fail-safe dispatch). It is already wired into production at
`worker/content_cycle.py:1153-1226`, gated by `settings.presentation_director_mode` (`"off"` /
`"shadow"` / `"enforce"`, currently **`"off"` in this environment** - built, tested, dormant, not
deleted). `services/event_recap_processor.py`'s own Tier-3 media fallback
(`render_recap_fallback_card()`) already reuses this SAME renderer module.

This is NOT a coincidence or a naming collision - it is the same product idea (thin pulse-line
device, minimal red/white NNJ branding, per-type variants), built earlier, currently switched off.
Building a second, parallel compositor for the new asset pack would directly violate this task's
own "do not build a second visual system if one already exists" rule.

**What the new asset pack (`assets/brand/newsroom_visuals/v1/`) actually adds** that the existing
system does not have today:
- Real, art-directed overlay graphics (quote marks, data ticks, a breaking ribbon, corner
  accents) instead of `brand_renderer.py`'s own hand-drawn primitives (`_draw_pulse_line()`,
  plain `ImageDraw` text).
- A visually richer QUOTE/DATA treatment than the current plain-text card.

**What does NOT change**: `presentation_director.py`'s classification logic
(`decide_presentation()`) is correct, evidence-grounded, and already reused by the master task's
own Stage 6 instruction ("do not introduce an independent visual classifier if the project already
has a presentation type") - it should be reused as-is, never rebuilt. The official-logo-handling
discipline in `brand_renderer.py` (official assets only, no redrawn/recolored logo, `_paste_logo()`
compositing `assets/brand/nnj_logo.png` verbatim) is already correct and already enforces exactly
the rule this task's own Stage 6 Section 21 asks for.

**A real, concrete blocker for a naive "just swap the assets in" plan**: `brand_renderer.py`'s
existing card canvas is `1200x675` (16:9, `_CARD_WIDTH`/`_CARD_HEIGHT`) for DATA/QUOTE/BREAKING,
and NEWS renders directly onto the source photo's own native aspect ratio. The new overlay pack is
`1122x1402` (4:5, portrait) - a fundamentally different canvas shape. Naively compositing a 4:5
overlay onto a 16:9 card would require either stretching the overlay (explicitly forbidden by this
task's own Section 20: "do NOT stretch an overlay to arbitrary ratios if that visibly damages it")
or redesigning `brand_renderer.py`'s own canvas geometry - a real architectural decision, not a
detail to resolve silently inside an asset-organization phase.

**Resolved (Phase V1 product decision)**: canvas stays 16:9/dynamic-source, unchanged - option (b)
above, effectively, though without commissioning a 16:9 overlay pack either. Instead of
compositing the 4:5 PNG pack directly, the approved minimal visual LANGUAGE it demonstrates (thin
bottom line + small pulse + small logo, restraint, adaptive contrast) was **recreated
deterministically inside `brand_renderer.py` itself** - `render_news_hero()` and
`render_breaking_frame()` were simplified/adjusted in place; `render_data_card()` /
`render_quote_card()` / `render_recap_fallback_card()` were left untouched (already correct, see
§4). The 4:5 pack now carries `asset_role: design_reference` /
`production_runtime_asset: false` in its own manifest - direction, not literal runtime assets. See
§4/§7 for the resulting per-type behavior and the new deterministic RED/WHITE adaptive palette.

## 3. Asset pack (Stage 2, complete)

Location: `assets/brand/newsroom_visuals/v1/`. Manifest: `manifests/overlays.yaml` (10 active
production overlays across UNIVERSAL/BREAKING/QUOTE/DATA; zero for NEWS - falls back to UNIVERSAL
by design; zero for RECAP - not manufactured, a real gap). All at 1122x1402 (4:5), genuine RGBA
with real (non-solid-black) alpha usage, zero exact duplicates.

**Branding-authenticity finding (Stage 2 Section 6)**: none of the "nnj" wordmarks baked into
these 11 source PNGs are proven pixel/vector-identical to the canonical assets
(`assets/brand/nnj_logo.png` / `.svg` / `_red.svg`). A direct crop-and-resize pixel comparison of
the one asset carrying a full logo badge (`references/badge_logo_variant_unverified_branding.png`)
against the canonical PNG showed a visually close but demonstrably different rendering: softer/
blurred edges, a missing dot-over-"j" accent the canonical mark has, and slightly different corner
geometry - consistent with an AI-regenerated approximation, not a composited reuse of the real
asset. Every overlay's manifest entry carries `contains_trusted_branding: false` accordingly. Per
Stage 2 Section 6/Stage 6 Section 21: any production compositor must add the real canonical logo
separately (reusing `brand_renderer.py`'s own existing `_paste_logo()`/`load_brand_mark()`
verbatim) rather than trust any embedded wordmark in this pack as the brand mark.

## 4. Presentation-type rules (Phase V1 implemented state)

Reuses `services/presentation_director.py::decide_presentation()`'s existing classification
unchanged (zero edits to that file) - NEWS/BREAKING/DATA/QUOTE are decided there today; a future
RECAP case would reuse EVENT_RECAP's own existing pipeline state (never re-derived here).

- **NEWS** - default, and now the actually-minimal treatment the prototype demonstrates:
  `render_news_hero()` composites only the official logo (bottom-right) and, for non-MINIMAL
  branding strength, one thin pulse line (bottom-left) in a deterministically-chosen RED or WHITE
  (§7). The previous `category · editorial_code` corner text label is removed entirely - the
  prototype bakes no text into the photo. No dedicated NEWS overlay asset exists or is needed
  (falls back to this same minimal treatment by construction, not a manifest fallback).
- **BREAKING** - still only ever selected via `presentation_director.py`'s own existing guard
  (MAJOR treatment + score floor + landmark keyword + named company); the visual layer never
  invents BREAKING status. `render_breaking_frame()` was simplified to stay in the SAME minimal
  family as NEWS: same adaptive pulse-line logic, just a wider/thicker line and one small urgency
  dot at its start, plus a slightly larger logo. The previous dark-gradient band + "BREAKING" text
  banner is retired - not approved against the real prototype (`breaking_minimal_01` in the
  overlay manifest is now `production_approved: false`, kept for design history only).
- **QUOTE** - unchanged. `render_quote_card()` never used the experimental quote-mark PNG pack at
  all (confirmed by direct source inspection - no `_draw_pulse_line`/overlay-compositing call
  exists in it) and already matches the prototype's own restrained portrait + Telegram-native-text
  treatment. `quote_minimal_01/02/03` are marked `production_approved: false` in the manifest -
  their oversized decorative quotation-mark glyphs don't match the prototype either.
- **DATA** - unchanged. `render_data_card()`'s existing deterministic number/label/chart rendering
  (`ImageDraw.text()` from already-cross-verified `DataCandidate` fields) was already close to the
  prototype's own DATA treatment (verified visually in the Phase V1 local preview set) and needed
  no change.
- **RECAP** - unchanged. `render_recap_fallback_card()`'s existing Tier-3 EVENT_RECAP fallback
  card was already close to the prototype's own RECAP example (verified in the local preview set)
  and needed no change. Still no dedicated RECAP overlay asset - not a blocker.

## 5. Album/video/Telegram rules (unchanged from the existing system)

- Only the first/cover image of a Telegram album would ever be branded (matches
  `brand_renderer.py`'s own existing one-image-at-a-time contract; no album-branding code exists
  today to change).
- No video overlay burn-in; a branded poster/thumbnail only, and only if this pack is ever wired
  in - no such capability exists today.
- No Telegram UI (buttons, reaction counters, subscribe CTA, message chrome) is ever drawn into
  the image. The EventRecap review's native "🔗 Источник" button (Phase I.2.2L,
  `bot/keyboards/event_recap_review.py`) remains real Telegram UI, never rendered into pixels.

## 6. Production visual composer prompt (Stage 5)

**File-format finding**: the repository's one existing versioned-YAML-prompt convention
(`prompts/<name>/v<N>.yaml` + `integrations/prompts/file_repository.py`) requires a mandatory
`output_schema: dict[str, Any]` field (`integrations/prompts/protocol.py::RenderedPrompt`) - built
specifically for structured JSON chat completions, not image generation. This is exactly why the
one real image-generation prompt precedent in this codebase,
`services/meme_image_generation.py::build_image_prompt()`, is a **plain, versionless Python
function** co-located with its caller, not a YAML file. Force-fitting a `prompts/visual_composer/
v1.yaml` file with a dummy `output_schema` would misrepresent what this prompt actually is. This
document therefore specifies the prompt CONTRACT below as the source of truth; when Stage 7 is
explicitly authorized, it should be implemented as a plain `build_visual_composition_prompt()`
function mirroring `build_image_prompt()`'s own shape and docstring discipline - not a new prompt
file.

The contract text supplied by the product owner (source fidelity, no invented product features,
no hallucinated logo/text/headlines/exact numbers, bottom safe area, minimalist premium style,
per-presentation-type behavior, multi-source handling, conservative fail-safe) is adopted verbatim
as the eventual `build_visual_composition_prompt()` contract, with no weakening. It is reproduced
in full in the master task transcript and is not duplicated here to avoid drift between two
copies; the implementing phase should copy it directly from that transcript into the function's
own docstring/return value, exactly as `build_image_prompt()` already does for its own (much
shorter) contract.

## 7. Deterministic RED/WHITE adaptive palette (Phase V1, implemented)

`services/brand_renderer.py::_choose_accent_color(canvas)`: a pure function of already-rendered
pixels, never an LLM call, never `random`, never a filename/metadata heuristic. Inspects the mean
perceptual luminance (ITU-R BT.601 weights, downsampled to a 32-wide grid) of the canvas's own
bottom ~15% (`_BRAND_SAFE_REGION_FRACTION`) - the exact region the pulse line is about to be drawn
into. RED (`_OFFICIAL_NNJ_RED`) is selected whenever that luminance is at or above
`_LUMINANCE_DARK_THRESHOLD = 96.0` (0-255 scale, roughly the low-mid range - documented in the
module itself, not an unexplained magic number); WHITE only when the region is clearly darker than
that. Same input always yields the same output. Applied only to `render_news_hero()`/
`render_breaking_frame()` (the two treatments that composite onto a real, variable-luminance
source photo) - `render_data_card()`/`render_quote_card()`/`render_recap_fallback_card()` render
onto this module's own fixed black canvas and are deliberately left untouched (always
correctly RED-on-black already, confirmed by direct source inspection that neither calls the new
function at all).

**Logo asset**: kept as the single existing `nnj_logo.png` (self-contained red badge + white
wordmark) for BOTH RED and WHITE pulse-line modes - a deliberate, disclosed decision, not a literal
reading of "logo = the white-compatible asset." No white/transparent raster logo variant exists
(only `nnj_logo.svg`, and this module has no SVG rasterizer installed - a pre-existing, deliberate
constraint documented in its own module docstring, and adding one would be new-dependency scope
creep this phase doesn't authorize). The existing badge is legible against any background by
construction (it carries its own opaque red square), so it needs no second variant - matches the
module's own pre-existing, already-tested "only ONE brand-mark placement, never a separate
white/red choice" decision, which a prior attempt at recoloring the PNG already broke (see the
module's own docstring for that forensic finding). Flagged here explicitly for product awareness.

## 7a. Design-reference overlay pack status (superseded, not deleted)

`manifests/overlays.yaml`'s 10 entries are `asset_role: design_reference` /
`production_runtime_asset: false` - they informed the reconciliation above but are not composited
at runtime. If an exact 16:9 overlay pack is supplied in a future phase, direct compositing may
become viable then - not decided or implemented here.

## 8. Cost containment / fail-open (unchanged from the existing system's own established discipline)

`brand_renderer.py::render_branded_media()` already never raises - any failure degrades to the
original unbranded media, logged, never blocking delivery (`RenderResult(success=False, ...)`).
Any future overlay-compositing addition must preserve this exact contract. Visual
generation/compositing must only ever run after existing editorial selection has already decided
to deliver a story - never during shadow ingestion, Story Memory building, or raw NEWS_ANALYSIS
candidate creation (`brand_renderer.py`'s current call site already satisfies this: it fires only
inside `worker/content_cycle.py`'s live-delivery path, gated by `presentation_director_mode`).
