# TELEGRAM-DATA-SEMANTIC-OVERFLOW-HOTFIX-1

Surgical production defect fix for a real, escaped Telegram DATA card: title "Все EUV-сканеры ASML
расписаны до конца 2027 года", primary value "94", giant red unit text overflowing the canvas edge
("% РЫНКА ЛИТОГР..."), a malformed white label ("ПОКАЗАТЕЛЬ ASML КОНТРОЛИРУЕТ ПРИМЕРНО РЫНКА..."),
and evidence copy that read as a near-duplicate of the label. This is a semantic-input + fail-closed
layout-safety fix only — DATA is not redesigned, and Telegram V8's canvas/fonts/grid/colors/graph
geometry/branding are untouched.

Branch: `feature/telegram-data-semantic-overflow-hotfix-1`
Base: `39f764b` (docs-only above the live production release `77a105f`)

---

## A. Current-head reconciliation

Verified against the CURRENT HEAD of the five named files (not assumed from the brief) before
writing any code:

| Function named in the brief | Present at HEAD? | Behavior |
|---|---|---|
| `services/editorial_pipeline/content.py::_extract_full_unit_text()` | Yes | `re.search(re.escape(value) + r"\.?\s*([^()]{1,40})", fact)` — scans up to 40 ARBITRARY characters of trailing prose, exactly as described. |
| `services/editorial_pipeline/content.py::_extract_subject_from_title()` / `subject = ... or legacy.label` | Yes | Falls back to `legacy.label` (a stripped remainder of the whole fact sentence) whenever the title has no "Model 9"-shaped match. |
| `services/brand_renderer.py::_fit_single_line()` | Yes | Returns `font_min`'s font even when `draw.textlength(text, font) > max_width` still holds — its own docstring discloses this ("Returns the smallest size actually tried even if `font_min` still does not fit"). |
| `services/render_evidence.py::_derive_data_hero_evidence()` | Yes | `text_clipped=False` hard-coded; the function did not even replay the `unit` fit at all (only `value`). |

All four root causes matched the brief's description exactly — no drift from the brief's assumed
code shape was found. `services/editorial_pipeline/telegram_integration.py` and
`services/editorial_pipeline/quality.py` were also inspected; neither needed changes (see §K).

One additional, load-bearing fact found during reconciliation, not named in the brief: a **second**
existing module, `services/editorial_pipeline/language_qa.py` (S22), already independently
discovered and documented the exact same "юань was never a recognized currency word" gap in
`services.presentation_director._CURRENCY_WORD`, and — critically — already established the
**precedent this hotfix follows**: fix the vocabulary gap LOCALLY, inside the new pipeline's own
module, never by editing `services/presentation_director.py`'s shared constants directly, because
that module's `_CURRENCY_WORD` is still load-bearing for the separate, frozen, currently-deployed
legacy V8 renderer path (S18's own `EXISTING_V8_MEDIA_BACKED_PIXEL_DIFF=0` freeze). This hotfix
extends that same established local-vocabulary pattern rather than inventing a new one.

## B. Real ASML reproduction

Reproduced end-to-end through the real production entrypoint, `build_structured_data_content()`,
using a title/fact pair equivalent to the real card (see
`tests/test_telegram_data_semantic_overflow_hotfix_1.py`'s `_ASML_TITLE`/`_ASML_FACT`/`_ASML_BODY`).

Against the UNMODIFIED pre-fix code (loaded directly from git commit `39f764b` for fidelity — see
`artifacts/telegram_data_semantic_overflow_hotfix_1/BEFORE_ASML.jpg`, rendered by the actual old
`render_data_hero_card()`):

```
metric_value = "94"
metric_unit  = "% рынка литографических сканеров, необхо"      (40-char arbitrary scan)
metric_label = "Показатель ASML контролирует примерно рынка литографических сканеров, необходимых для произ"
subject      = "ASML контролирует примерно рынка литографических сканеров, необходимых для произ"
```

`BEFORE_ASML.jpg` visually reproduces every symptom named in the brief: giant red unit text
overflowing past the right canvas edge, the malformed white label, and evidence copy that reads as
a near-duplicate of the label/unit text.

`ASML_DEFECT_REPRODUCED = true`

## C. Exact semantic root cause

Two independent defects in `services/editorial_pipeline/content.py::build_structured_data_content()`
(both confirmed via direct reproduction, not assumed):

1. **Unit extraction was syntactic, not semantic.** `_extract_full_unit_text()` ignored the already
   grounded, cross-verified `legacy.unit` (`services.presentation_director._find_data_candidate()`'s
   own output — confirmed by direct call: `legacy.unit == "%"` for the ASML fact, already correct)
   and instead re-scanned up to 40 arbitrary characters of trailing prose after the numeric value.
   For a percentage/change unit, that arbitrary scan is *pure* overflow risk — there is nothing to
   fix, `legacy.unit` was already complete.

2. **Subject extraction had no safe fallback.** `_extract_subject_from_title()` only recognized a
   "Model 9"-shaped title token (`[A-Z][a-zA-Z]*\s+\d+`) — structurally unable to match an
   acronym-only company name like "ASML" (no trailing digit). Its caller then fell back to
   `legacy.label`, the (unfixed, for this fact) old extractor's own stripped-sentence remainder,
   which became both the DATA `subject` and, via string interpolation, most of the visible
   `metric_label`.

`UNIT_CONTAINS_TRAILING_PROSE_BEFORE_FIX = true`
`SUBJECT_USES_SENTENCE_FALLBACK_BEFORE_FIX = true`

## D. Unit extraction fix

`_extract_full_unit_text(fact, value, legacy_unit)` (signature changed - it now takes the grounded
`legacy_unit` as its base authority, never re-derives it from scratch):

- A **change/percentage unit** (`_is_change_unit()`, reused verbatim from
  `services.presentation_director` — the SAME classification the legacy extractor itself already
  uses) is returned **unchanged, with no scan at all**. This alone fixes ASML: `legacy_unit == "%"`
  passes straight through.
- A **magnitude unit** (тыс/млн/млрд/k) that the legacy extractor already paired with a currency
  word (`_extend_span_with_currency`, e.g. "25 млн долларов" → `unit="млн долларов"`) is also
  returned unchanged — nothing to add.
- Only a magnitude unit **not yet** paired with a currency word may gain **one** bounded,
  semantically-recognized currency token immediately following its own occurrence in `fact` — never
  more than one token, never arbitrary trailing text. The currency grammar is a **local** extension
  of `services.presentation_director._CURRENCY_WORD` (adds юань/yuan/rmb/cny/¥), following the exact
  precedent `services/editorial_pipeline/language_qa.py` already established for the same gap — the
  shared, legacy-V8-load-bearing constant in `presentation_director.py` is never touched.

No character-count truncation (`unit[:10]`) anywhere. No ASML-specific or any other company/product
special-casing anywhere in the diff (verified: `grep -i "asml\|euv"` over the changed production
files returns nothing outside test fixtures and comments describing the historical defect).

`UNIT_CONTAINS_TRAILING_PROSE = false`
`UNIT_OVERFLOW_POSSIBLE = false` (the change-unit branch never scans; the magnitude branch only ever
appends one bounded, grammar-recognized token — see §G's regression matrix for the currency cases)

## E. Subject/metric-label fix

`_extract_subject_from_title(title, fact)` (signature changed — now takes the grounding `fact` too):

1. The existing "Model 9"-shaped match is tried first, unchanged (Maxus 9 still matches here, no
   regression).
2. If that fails, a bounded, **generic** all-caps-acronym shape (`\b[A-Z]{2,}\b`) is tried, but only
   ever accepted when the SAME acronym appears in **both** the title and the grounding fact —
   cross-verified, mirroring the whole module's own "grounded in two independent places" discipline
   already applied to the numeric value. A small, generic, non-brand-specific set of acronyms that
   are never themselves a real subject (AI, EU, US, UK, USD, EUR, GPU, CPU, CEO, CTO, IPO, API, OS)
   is excluded — the same structural, non-denylist judgment
   `services.editorial_pipeline.subject_extraction` already makes independently for the same reason.
3. If NEITHER tier finds anything, `_extract_subject_from_title()` returns `None` — and the caller
   (`build_structured_data_content()`) now uses a **kind-only label** (e.g. "Доля рынка") instead of
   ever falling back to `legacy.label`. `StructuredDataContent.subject` becomes `""` in that case
   (not used by any renderer today — confirmed by grep; it is a traceability field only).

For the real ASML case: `subject == "ASML"`, `metric_label == "Доля рынка ASML"` — the exact
acceptable form named in the brief.

No brand/company/product name (ASML, EUV, Apple, OpenAI, or any other) is hard-coded anywhere in the
diff — the acronym mechanism recognizes a SHAPE, cross-verified against real evidence, exactly like
`_MODEL_NAME_RE` already did for versioned product names.

`SUBJECT_USES_SENTENCE_FALLBACK = false`

### §6 — market-share metric kind

`_classify_metric_kind(fact_lower, unit)` gained one new, generic, evidence-driven branch: a
grounded change/percentage unit (`_is_change_unit(unit)`) together with a generic Russian "market"
stem (`рынк` — matches рынок/рынка/рынке/рынку/рынков) now classifies as `"Доля рынка"`. The four
pre-existing kinds (Стартовая цена, Цена, Запас хода, Время зарядки) are unchanged, verified by the
unchanged Maxus regression (§H) and the untouched code paths for those branches.

## F. Renderer fail-closed guard

`services/brand_renderer.py::render_data_hero_card()`: a new helper,
`_require_single_line_fits(draw, text, font, max_width, element)`, is called immediately after each
of the two `_fit_single_line()` calls for `value_text` and `unit_text` (the two MANDATORY hero
elements named in the brief). It re-measures `draw.textlength(text, font)` against `left_col_w` and
`raise`s a `ValueError` if the fitted font still does not fit — before either element is drawn.

`_fit_single_line()` itself is **unchanged** (still shared with `render_quote_card()`, out of this
hotfix's scope, per the brief's own "do not globally break callers unnecessarily" instruction) — its
own disclosed fail-open behavior (returning `font_min` even when that still overflows) is exactly
what the new guard catches, one call site at a time, only for DATA's two mandatory elements.

The raise propagates naturally through `render_branded_media()`'s existing, pre-existing
`except Exception` boundary (services/brand_renderer.py:1849, unmodified) — which already converts
any DATA-render exception into `RenderResult(success=False, ...)`. `telegram_integration.py`'s
`_render()` callback (unmodified) already converts `not render_result.success` into `return None`,
and `orchestrator.py` (unmodified) already converts a `None` render outcome into
`RecoveryReasonCode.RENDER_FAILED` → HOLD/recovery. **No new plumbing was needed** — the unified
pipeline's existing fail-safe wiring already did the right thing the moment the renderer started
raising instead of silently drawing.

No canvas widening, no boundary movement, no shrinking past the existing `_HERO_VALUE_FONT_MIN`/
unit `24`px floors, no cropping, no drawing past the canvas — confirmed by inspection: the change is
purely an added measurement-and-raise, zero geometry constants touched.

`VALUE_OVERFLOW_POSSIBLE = false`
`UNIT_OVERFLOW_POSSIBLE = false`

## G. RenderEvidence correction

`services/render_evidence.py::_derive_data_hero_evidence()`: previously replayed only the `value`
fit and hard-coded `text_clipped=False` regardless. Now replays **both** mandatory elements — the
`unit` fit was not replayed at all before this fix — against the exact same `inner_w` the renderer
itself draws into, and sets `text_clipped = value_clipped or unit_clipped` from real
`draw.textlength()` measurements, never a hard-coded sentinel.

`RENDER_EVIDENCE_CAN_FALSE_PASS_OVERFLOW = false`

## H. Maxus non-regression

The real, independently-fetched Maxus 9 fact (`tests/test_editorial_pipeline_data_content.py`,
unchanged) still produces, after this hotfix:

```
metric_value = "290"
metric_unit  = "тыс юаней"
metric_label = "Стартовая цена Maxus 9"
subject      = "Maxus 9"
```

Byte-identical to the pre-hotfix behavior for this fact. `tests/test_editorial_pipeline_data_content.py`
and `tests/test_editorial_pipeline_language_qa.py` (which independently pins the "юань"/"с юаней"
gap this hotfix also touches) both pass unchanged.

`MAXUS_290_THOUSAND_YUAN_PRESERVED = true`

## I. Corrected ASML artifact

`artifacts/telegram_data_semantic_overflow_hotfix_1/`:

- `BEFORE_ASML.jpg` — rendered with the actual PRE-FIX code (loaded directly from git `39f764b`,
  not hand-simulated) fed the real ASML title/fact. Reproduces every symptom in the brief.
- `AFTER_ASML.jpg` — rendered with the FIXED pipeline, same title/fact. Shows: `94` as the metric,
  `%` as the unit (no overflow, no trailing prose), the concise label "ДОЛЯ РЫНКА ASML", no
  right-edge overflow, no malformed/repeated label text.
- `ASML_STRUCTURED_CONTENT.txt` — the exact title/fact/body inputs and the resulting structured
  content fields.
- `geometry_evidence.json` — the real `RenderEvidence` for the AFTER render:
  `text_clipped: false`, `primary_font_size: 270`, `canvas: 1280x1172`, `metric_unit: "%"`,
  `metric_label: "Доля рынка ASML"`.

No secrets in any artifact file.

## J. Tests

New: `tests/test_telegram_data_semantic_overflow_hotfix_1.py` (10 tests) — the full regression
matrix from the brief:

- A. Real ASML replay (unit stays bounded, label concise/non-malformed, hero text fits — 3 tests)
- B. Maxus replay stays fixed (1 test)
- C. Percentage never absorbs trailing prose (1 test)
- D. Currency magnitude preserved — million dollars, billion rubles (2 tests)
- E. Pathological `DataCandidate` fails closed at the renderer (1 test)
- F. RenderEvidence never false-passes the same pathological candidate (1 test)
- G. A normal, already-fitting candidate's render is unaffected/deterministic (1 test)

Strengthened per §9: `tests/test_founder_visual_board_alignment_1.py`'s
`test_hero_card_fits_a_very_long_value_without_clipping` was a **real, pre-existing false positive**
— its own fixture (`unit="ПОЛЬЗОВАТЕЛЕЙ В МЕСЯЦ"`) already overflowed both `value` (817px) and `unit`
(578px) against a 449px column, and the test only asserted the hard-coded `text_clipped=False`
sentinel, never actual geometry. Replaced with two tests: one proving a genuinely fitting case
against real measured `draw.textlength()` geometry, and one proving the old fixture now correctly
fails closed (`render_data_hero_card()` raises) and is truthfully reported as clipped.

Targeted suites run: `tests/test_editorial_pipeline_data_content.py`,
`tests/test_editorial_pipeline_language_qa.py`, `tests/test_founder_visual_board_alignment_1.py`,
`tests/test_render_evidence_parity.py`, `tests/test_design_spec_enforcement.py`,
`tests/test_unified_pipeline_subject_extraction.py`, `tests/test_telegram_data_semantic_overflow_hotfix_1.py`
— **97 passed, 0 failed**.

Broad regression: full `tests/` suite run (excluding four test files that fail to even COLLECT on
the unmodified base commit `39f764b` itself — `test_phase20_m1_harness_fixes.py`,
`test_v2_3a_editorial_recomposition_canary.py`, `test_v2_4d_overlay_contract.py`,
`test_v2_4f_compact_overlay.py` — confirmed by running the identical collection against the
pre-existing `ai-newsroom-unified-pipeline-vision-gate-closure-1` worktree at `39f764b`, which
fails identically; a `scripts`-package/asset-path environment gap unrelated to this diff): **6662
passed, 52 failed, 28 skipped** on the first pass.

All 52 failures were individually triaged against the unmodified base commit `39f764b`:

- **4 were real regressions**, all in `tests/test_brand_renderer.py` (a file the brief's own
  "relevant brand_renderer DATA tests" names covers), all caused by the SAME new fail-closed guard
  (§F) correctly firing on **pre-existing, latent overflow** in four legacy test fixtures that
  predate the V2.20 board-aligned hero-card layout: `unit="million"` (English, 7 letters) measured
  557px against the 449px approved column at the value-scaled unit font size, and
  `value="14,500,000"` (a full 10-digit comma-formatted integer) measured 582px — both already
  overflowing (confirmed via direct `_fit_single_line`/`textlength` replay against the SAME,
  UNCHANGED `_fit_single_line()`) before this hotfix ever touched the file; the new guard simply
  made the pre-existing overflow visible instead of silently clipping it, exactly the defect class
  this hotfix exists to catch, just discovered in more than the one ASML-shaped location. Fixed
  the SAME way as §9's `test_founder_visual_board_alignment_1.py` false-positive: the incidental
  English/oversized fixture text (`"million"` → `"млн"`, matching this renderer's real, only-ever
  Russian production unit vocabulary; `"14,500,000"` → `"145,000"`, the largest comma-formatted
  integer that measurably fits, still exercising each test's own actual, unchanged assertions) was
  swapped for realistic, genuinely-fitting text — no test assertion, renderer code, or DATA geometry
  constant was touched to make these pass. `tests/test_brand_renderer.py` now passes 79/79, matching
  its base-commit pass count exactly.
- **48 are pre-existing, environment-caused failures**, confirmed NOT caused by this diff:
  15 fail identically on the unmodified base commit's own worktree (shared local Postgres
  test-database foreign-key/state pollution from the full-suite run, e.g.
  `IntegrityError: ... still referenced from table "image_candidates"` — a full-suite-only
  cross-test DB-isolation artifact, unrelated to any file this hotfix touches); the remaining 33 are
  DB-state-order-dependent flakes that reproduce on base when run in the same full-suite order but
  PASS in isolation on both base and this branch (verified directly, batch by batch, for every one
  of the 48) — none touch `content.py`, `brand_renderer.py`, or `render_evidence.py` at all.

`ruff check` and `mypy` both clean on all three touched production files.

`NEW_FAILURES = 0`

## K. Unchanged systems

Confirmed by `git diff --stat` against base `39f764b`: exactly three production files touched
(`services/editorial_pipeline/content.py`, `services/brand_renderer.py`,
`services/render_evidence.py`), two existing test files strengthened/fixed
(`tests/test_founder_visual_board_alignment_1.py` per §9,
`tests/test_brand_renderer.py` per §J's latent-fixture fixes), one new test file, plus the
artifacts/report. `services/presentation_director.py` (the legacy V8 DATA/BREAKING/QUOTE extractor
and renderer dispatch) is **not touched at all** — its `_CURRENCY_WORD`/`_find_data_candidate`/etc.
stay byte-for-byte frozen, so the legacy production render path (still live for any caller not
routed through the unified pipeline) is unaffected. `services/story_memory.py`, the arXiv identity
guard, `services/media_*` truthfulness/vision-gate modules, `services/editorial_pipeline/recovery*.py`,
Telegram transport, and every Instagram module are untouched — not present in the diff.

`TELEGRAM_V8_DESIGN_CHANGED = false`
`STORY_MEMORY_CHANGED = false`
`ARXIV_GUARD_CHANGED = false`
`VISION_GATE_CHANGED = false`
`TRANSPORT_CHANGED = false`
`INSTAGRAM_CHANGED = false`

## L. Production deployment recommendation

Do not deploy from this phase. Per the brief's own scope (§15), this phase ends at fix + tests +
corrected visual replay + report + pushed branch — no production restart, env change, container
rebuild, DB migration, or resend of the broken ASML post was performed. Recommend: Founder reviews
`AFTER_ASML.jpg` against the board-approved DATA template; on approval, deploy
`feature/telegram-data-semantic-overflow-hotfix-1` the same way `77a105f`/`39f764b` were deployed
(service-specific `content_worker` override, flag-off smoke gate first) — no new migration is
required (no schema touched).

---

## Final metrics

```
ASML_DEFECT_REPRODUCED=true
ASML_METRIC_VALUE=94
ASML_METRIC_UNIT=%
ASML_METRIC_LABEL=Доля рынка ASML

UNIT_CONTAINS_TRAILING_PROSE=false
SUBJECT_USES_SENTENCE_FALLBACK=false

VALUE_OVERFLOW_POSSIBLE=false
UNIT_OVERFLOW_POSSIBLE=false
RENDER_EVIDENCE_CAN_FALSE_PASS_OVERFLOW=false

MAXUS_290_THOUSAND_YUAN_PRESERVED=true

TELEGRAM_V8_DESIGN_CHANGED=false
STORY_MEMORY_CHANGED=false
ARXIV_GUARD_CHANGED=false
VISION_GATE_CHANGED=false
TRANSPORT_CHANGED=false
INSTAGRAM_CHANGED=false

NEW_FAILURES=0
```

## Final verdict

**TELEGRAM_DATA_SEMANTIC_OVERFLOW_HOTFIX_READY_FOR_FOUNDER_REVIEW**
