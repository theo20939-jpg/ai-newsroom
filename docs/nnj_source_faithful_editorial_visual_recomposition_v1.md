# NNJ Source-Faithful Editorial Visual Recomposition v1

Status: **design document only. No code implements this capability yet. No production wiring,
no live provider, no LLM/image-generation API call has been made while writing this document.**
This is a companion to, not a replacement for,
[`docs/nnj_editorial_visual_system_v1.md`](nnj_editorial_visual_system_v1.md) - see §14 for how
the two relate.

## 1. Purpose

For some stories - especially hero product/gadget news - simply overlaying the NNJ brand line on
top of a raw, as-fetched source photo is not always the best achievable result: the photo may be
cluttered, awkwardly cropped, or have its own busy background that fights the overlay (exactly the
contrast problems the V1 bright/graphite comparative proof measured directly). This capability
would let the system, for eligible stories only, treat the selected source image as a **factual
visual reference** rather than a final composition - isolating the real subject, cleaning or
replacing the background, and reframing it into a calmer editorial scene - before the existing
deterministic NNJ brand layer is applied. The source image remains the *ground truth* for what the
subject actually looks like at all times; only the *composition* around it may improve.

## 2. When to use recomposition

Likely-positive candidates (documented in full in §5):
- hero product/hardware news (phone, laptop, gadget launches) with a clean single-subject photo;
- major portraits/interviews where a calmer background would help;
- strong single-subject technology imagery with a busy or awkward background.

## 3. When NOT to use recomposition

- dense infographics or charts where the exact original numbers/layout **are** the story;
- screenshots where the UI/text itself is the evidence;
- scenes whose factual meaning depends on the exact original composition (e.g. a courtroom photo,
  a specific multi-person arrangement);
- images with insufficient source fidelity to begin with (already low-resolution, already heavily
  compressed, ambiguous subject);
- anything DATA/QUOTE already renders deterministically from text (`render_data_card()`,
  `render_quote_card()`) - those have no photographic subject to recompose in the first place.

## 4. Allowed transforms

- isolate the main subject from its background;
- remove background clutter;
- replace the background with a neutral/editorial one;
- extend the background where needed for reframing;
- subtly re-light (never recolor the subject itself);
- reframe, reposition, slightly rotate, or rescale the subject;
- create negative space;
- reserve a calm lower zone for the deterministic NNJ brand layer (§8).

## 5. Forbidden transforms (hard rule: FACTUAL VISUAL FIDELITY)

- inventing new cameras, buttons, ports, or any hardware detail not visible in the source;
- changing the device model or its official shape;
- altering a real person's identity or facial characteristics;
- changing an official product's color where that color is factually part of the story;
- fabricating a screen/UI that was not present in the source;
- adding imaginary product details or features;
- changing or redrawing any logo/branding visible in the source evidence itself (a competitor's
  logo, a product's own branding - this is a *separate* rule from the NNJ brand layer in §8, which
  the recomposition step must never touch at all);
- depicting a non-existent/future/unreleased product appearance from text alone.

If truthful recomposition is not achievable within these rules for a given image, the system must
fall back to the existing conservative crop/overlay treatment (§9) - never fabricate to compensate.

## 6. Factual fidelity rules

The source image(s) are the source of truth for: people, devices, product appearance, event
scenes, and any logos already present in the evidence. The recomposition step may change *how* the
subject is framed and *what surrounds it*; it may never change *what the subject actually is*.
This mirrors, and is strictly narrower than, the general "source fidelity" principle already
established for NEWS/QUOTE copy in this codebase (never fabricate facts not in evidence) - applied
here to pixels instead of text.

## 7. Safe-zone / composition rules

Reserve the lower ~10-15% of the frame as a calm, uncluttered zone reserved for the deterministic
NNJ brand layer - the same `_BRAND_SAFE_REGION_FRACTION = 0.15` convention
`services/brand_renderer.py::_choose_accent_color()` already established for the V1 adaptive
RED/WHITE palette logic (see that module for the precedent). No essential subject detail, face, or
required product feature may be placed inside that reserved zone.

## 8. Interaction with deterministic NNJ branding

Recomposition happens **strictly before** and is **strictly separate from** the existing
deterministic NNJ brand layer (`services/brand_renderer.py`). The recomposition step must never
generate the NNJ logo, the pulse line, or any brand mark itself - all brand identity remains
100% deterministic Pillow compositing exactly as V1 established, applied *after* recomposition
produces a clean base image. This is the same discipline `services/meme_image_generation.py::
build_image_prompt()` already established for its own (unrelated) generation step: "generate
WITHOUT any text baked in... M6's renderer is the only place overlay text is ever added" - applied
here to brand marks instead of meme captions.

## 9. Fail-open behavior

If recomposition fails, times out, is judged unsafe (§8 of the master task; see also `docs/
nnj_editorial_visual_system_v1.md`'s own `RenderResult(success=False, ...)` fail-safe precedent),
or is simply not attempted (ineligible story), the pipeline must fall back to the existing,
already-proven-safe conservative treatment: the selected source image composited with the
deterministic NNJ overlay/brand layer exactly as `brand_renderer.py` already does today. Never:
block the news item, fabricate a blank/placeholder image, or degrade evidence integrity. This
exactly mirrors `render_branded_media()`'s own existing "a rendering problem always degrades to
the original unbranded media, never blocks delivery" contract - recomposition sits as one more
optional, fail-open stage ahead of that same guarantee, not a replacement for it.

## 10. Cost containment / gating

Mirrors `services/meme_image_generation.py`'s own already-established discipline exactly:
- a plain mode setting (`Literal["off", "dry_run", ...]`, matching `meme_image_generation_mode`'s
  own shape) gates the entire step; `"off"` is a zero-cost, zero-call no-op;
- recomposition is only ever attempted for a story that has *already* been selected for delivery
  (never during shadow ingestion, Story Memory building, or raw NEWS_ANALYSIS candidate creation) -
  the same rule V1's own `docs/nnj_editorial_visual_system_v1.md` §8 already established for the
  deterministic brand layer;
- bounded retries only (mirrors `_MAX_GENERATION_ATTEMPTS = 2`), never an unbounded loop;
- the eligibility/decision policy (§13) is itself a cost gate - most images should route to the
  existing conservative treatment, which costs nothing extra at all.

## 11. Usage modes

### Mode A - CONSERVATIVE OVERLAY MODE (existing, unchanged)

Use the selected source image largely as-is. May crop/reposition the frame (exactly what V1's own
local proofs already did with `cover_fit()`/anchor selection) but never alters subject pixels.
Then apply the existing deterministic NNJ brand layer (`brand_renderer.py`). This is the default,
always-safe mode - every story that doesn't clear the eligibility policy in §13 uses this mode,
unchanged from what already ships today.

### Mode B - SOURCE-FAITHFUL RECOMPOSITION MODE (new, not implemented)

Use the selected source image as factual visual evidence, not as the final composition. Extract/
recompose the subject into a cleaner editorial frame per §4/§5's allowed/forbidden transforms,
reserving the lower safe zone (§7). Then apply the identical deterministic NNJ brand layer Mode A
uses - the two modes converge on the exact same brand-application step, they differ only in what
happens to the base image before it.

## 12. Strict production prompt contract (not wired, not called)

Per the repository's own real precedent (`services/meme_image_generation.py::build_image_prompt()`
is a plain, versionless Python function, not a YAML prompt file - see `docs/
nnj_editorial_visual_system_v1.md` §6 for the full reasoning: `RenderedPrompt` requires a mandatory
`output_schema` built for structured JSON chat completions, which does not fit image generation).
This contract is documented here as the source of truth; when a future phase is explicitly
authorized to implement it, it should become a plain `build_recomposition_prompt()` function
mirroring `build_image_prompt()`'s own shape.

```
ROLE: You are the NNJ Source-Faithful Editorial Visual Composer.

MISSION: Create a cleaner editorial composition from real source media while preserving the
real factual appearance of the subject.

INPUTS: presentation_type; source image(s); story summary; known entities; optional output
size/aspect ratio; safe-zone requirement.

SOURCE FIDELITY: Treat source image(s) as the source of truth for people, devices, product
appearance, event scenes, logos present in evidence, interfaces/screens.

ALLOWED: isolate subject; remove clutter; replace background; extend background; re-light
subtly; reframe; reposition; rotate slightly; scale subject; create negative space; reserve
lower branding zone.

FORBIDDEN: invent product details; change hardware design; change human identity; fabricate UI;
alter logos; change official brand appearance; add missing features; create unsupported event
details; create fictional scenes that misrepresent the story.

BOTTOM SAFE ZONE: Leave a calm lower area for deterministic NNJ branding. Do not place crucial
details in the bottom brand zone.

TEXT RULE: Do not generate headlines. Do not generate article text. Do not generate fake
interface text. Do not render exact statistics. Do not render quote text.

NNJ BRAND RULE: Do not generate NNJ branding. Do not generate the NNJ logo. Do not generate the
pulse line. All NNJ branding is deterministic downstream (brand_renderer.py, unchanged).

FAIL-SAFE: If truthful recomposition is not possible, fall back conceptually to a cleaner
crop-based treatment of the source image rather than fabricating details.

OUTPUT: Only the recomposed visual. No explanations, no extra text, no branding.
```

## 13. Deterministic decision policy (rule-based, not ML, not activated)

A future eligibility check, evaluated per story, deciding `RECOMPOSE` vs `CONSERVATIVE_OVERLAY`
vs `DO_NOT_VISUALLY_ALTER` - rule-based, mirroring `services/presentation_director.py::
decide_presentation()`'s own established "deterministic guard, never ML" discipline exactly (that
module's own docstring: "AI is not a safety gate"). No new classifier model is needed or proposed.

Proposed inputs (all already available upstream, nothing new to compute):
- `presentation_type` (from the existing `decide_presentation()` output) - DATA and QUOTE-with-
  no-portrait never qualify (§3: nothing photographic to recompose, or the exact original
  composition IS the evidence);
- source image count / subject count - multiple ambiguous subjects in one frame → ineligible
  (see "Unsafe recomposition examples" below);
- whether the image is flagged as a screenshot/UI capture (if such a signal exists upstream) →
  ineligible, the UI/text itself may be the evidence;
- image quality/cleanliness signals already computed by `services/image_quality.py` /
  `services/media_ranking.py` (branding risk, quality score) - a low-quality or highly ambiguous
  source is a poor recomposition candidate and a poor conservative-crop candidate alike;
- editorial treatment tier (existing `services/editorial_treatment.py` MAJOR/STANDARD/BRIEF) -
  recomposition cost is only justified for stories already worth the strongest visual treatment.

Proposed decision shape (illustrative, not implemented):

```
if presentation_type in (DATA, QUOTE) and not hero_product_candidate:
    return DO_NOT_VISUALLY_ALTER  # or CONSERVATIVE_OVERLAY per existing behavior
if subject_count > 1 or is_screenshot_or_ui_capture or quality_score below floor:
    return CONSERVATIVE_OVERLAY  # safe default, never blocks delivery
if treatment == MAJOR and presentation_type in (NEWS, BREAKING) and single_clean_subject:
    return RECOMPOSE
return CONSERVATIVE_OVERLAY
```

`CONSERVATIVE_OVERLAY` remains the default in every ambiguous case - the policy only ever opts
*into* recomposition for a narrow, clearly-eligible subset, never the reverse.

### Unsafe recomposition examples (→ always CONSERVATIVE_OVERLAY or DO_NOT_VISUALLY_ALTER)

- multiple ambiguous devices/subjects in one frame;
- screenshot-heavy evidence where the critical fact is the exact UI text;
- an unclear/unconfirmed product model;
- a portrait where any risk of face distortion exists;
- any image whose meaning depends on its exact original composition (e.g. a courtroom scene, a
  specific multi-person arrangement, an exact chart/infographic).

## 14. How this connects to V1

V1 (`docs/nnj_editorial_visual_system_v1.md`) remains responsible for: the canonical visual
language, the bottom-line geometry, the RED/WHITE/GRAPHITE palette families, prototype alignment,
overlay/palette selection rules, and the deterministic brand layer itself
(`services/brand_renderer.py`). V2 (this document) adds one new, optional, earlier stage:
source-faithful recomposition of the *base image* before V1's brand layer is applied to it.

Combined future conceptual pipeline (not implemented, not wired):

```
selected factual media (existing, unchanged: media_ranking.py / image_persistence.py)
  -> risk/eligibility check (§7 below - NEW, not yet implemented)
  -> CONSERVATIVE mode (existing brand_renderer.py path, unchanged)
     or RECOMPOSITION mode (NEW, blocked pending a real image-editing provider - see §15)
  -> clean editorial composition (source-faithful, factual)
  -> deterministic NNJ brand layer (existing brand_renderer.py, unchanged - V1's RED/WHITE/
     GRAPHITE palette selection applies here exactly as today)
  -> existing send path (worker/content_cycle.py / event_recap_processor.py, unchanged)
```

Story Memory, media selection, media ranking, and editorial evidence integrity are never touched
by any part of this - recomposition only ever transforms the pixels of an already-selected image,
never which image was selected or why.

## 15. Proof / approval flow before production activation

1. This design document + prompt contract (§6 in the master task, reproduced in code comments
   where the future implementing phase adds `build_recomposition_prompt()`) reviewed and approved.
2. A real image-editing-capable provider (not the existing text-only mock) explicitly authorized,
   selected, and wired to `ImageGenerationGateway` - or that Protocol extended with a reference-
   image field first, since the current schema has none (see the Final Report's capability audit).
3. A bounded, explicitly-authorized local/dry-run proof using the real provider in a non-production
   mode (mirrors `meme_image_generation_mode: "off" | "dry_run"`'s own established precedent).
4. A single, explicitly-authorized live canary on one real story, mirroring the discipline already
   used for the very first EVENT_RECAP canary (Phase I.2.2K) and the still-dormant
   `presentation_director_mode: "shadow"` step before `"enforce"`.
5. Only after all of the above: any broader activation.

None of these steps happen in this phase.

## 16. Provider Selection — V2.2 Bake-Off (LOCKED)

Steps 1-2 of §15 are now complete: `ImageGenerationGateway`/`ImageGenerationRequest` were extended
with reference-image support (Phase V2.1), two real provider adapters were built and contract-
repaired against live traffic (Phase V2.1/V2.2A), and a real 3-source × 3-model = 9-cell live
bake-off was run and evaluated (Phase V2.2B, full evidence at
`docs/phase_v2_2b_complete_bakeoff_report.md` and
`assets/brand/newsroom_visuals/v2_2_bakeoff_complete/evaluation.json`). The model decision below is
now the authoritative, evidence-backed selection - **not yet wired to any production code path**
(§15 steps 3-5 remain outstanding).

**PRIMARY SELECTION CRITERION: factual fidelity, not aesthetic composition.**

**DEFAULT: `gemini-3.1-flash-image`**
- Mean factual fidelity 5.0, worst-case 5 - the only model with zero mutation flags of any
  severity across all 3 cases (zero CRITICAL, zero MAJOR, zero MINOR).
- Fastest of the three (mean 14.2s) and roughly half Gemini Pro's evaluated per-image cost.
- Strongest precision result of the whole bake-off on Case 2 (the geometry/detail-preservation
  case) - every keyboard key and the Duolingo wordmark/tagline preserved exactly.
- Estimated cost for its 3 successful bake-off outputs: **~$0.201 (ESTIMATE - not provider-reported)**.

**OPTIONAL FUTURE MANUAL COMPOSITION ESCALATION: `gemini-3-pro-image`**
- Mean factual fidelity 4.33 (lower than Flash), best mean composition score (4.0).
- Two `MINOR_VISUAL_MUTATION` findings (a lighting/material drift on Case 2's keyboard, a
  simplified on-screen photo on Case 3) - not disqualifying, but real.
- ~2× Flash's evaluated cost (~$0.402 for 3 outputs, ESTIMATE) and slower (mean 24.6s).
- **Not** an automatic escalation target - see §17. Available only for controlled, manually
  reviewed future use (e.g. a hero/editorial placement where the extra composition quality is
  worth a human double-check).

**NOT PRODUCTION-SELECTED: `gpt-image-2`**
- Mean factual fidelity 4.0, worst-case 3 - lowest of the three, and the bake-off's only
  `MAJOR_VISUAL_MUTATION`: on Case 2 it deleted the real keyboard entirely, replacing it with a
  flat solid-color background - a direct violation of this document's own source-fidelity
  requirement (§4/§5's ALLOWED/FORBIDDEN transforms).
- Best mean safe-zone score (4.33) and cheapest (~$0.15 for 3 outputs, ESTIMATE), but per the
  primary selection criterion those advantages do not offset a real factual-content-loss failure.
- Remains available as tested, provider-neutral infrastructure (`OpenAIImageAdapter` is not
  deleted) - just not configured as production default, automatic fallback, or automatic
  escalation model. This is a "not selected given current evidence" verdict, not a permanent ban;
  a larger future sample could revisit it.

**Billing disclosure, kept separate and never blended together**: none of the 9 successful bake-off
generations' dollar costs above are provider-reported - all are ESTIMATE, sourced from each
adapter's own dated pricing citation. Separately, the 12 Gemini attempts from the first, failed
V2.2 live run (before the contract repair) have **UNKNOWN** billing impact - a `usage` field was
present in those raw responses but never captured before the parsing failure; this must be checked
against the Google AI Studio / Cloud Billing console directly, and is never treated as $0.

## 17. Production Policy (LOCKED IN DOCUMENTATION ONLY - NOT IMPLEMENTED)

This is the authoritative future routing policy for whenever recomposition is actually wired to a
production path (§15 steps 3-5, still outstanding) - written here as a contract for that future
implementation, not as code, and not yet enforced anywhere:

- **Default model: `gemini-3.1-flash-image`.**
- **If a Flash generation fails** (any adapter-typed error, any bounded-retry exhaustion): **fail
  open to the existing conservative/deterministic media path** (the CONSERVATIVE mode in §14's
  pipeline diagram above, i.e. the current unmodified `brand_renderer.py` treatment of the
  already-selected source image) - exactly the same fail-open discipline
  `services/meme_image_generation.py` already established for meme generation.
- **A Flash failure must NEVER automatically fall back to `gemini-3-pro-image` or `gpt-image-2`.**
  A more "creative"/aggressive model is a higher factual-mutation-risk path, not a safer one - an
  automatic escalation on failure would silently trade reliability for mutation risk, backwards
  from what a failure-handling fallback should do.
- **Gemini Pro escalation stays manual and separately controlled** - e.g. a future explicit,
  human-selected flag or editorial decision per story, never an automatic routing rule triggered
  by image content, difficulty, or a prior model's failure.
