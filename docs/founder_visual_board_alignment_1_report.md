# FOUNDER-VISUAL-BOARD-ALIGNMENT-1 — report

Final Founder visual alignment for NINJA PULSE Telegram rendering, against the **real
Founder-approved board** supplied on disk. Follows `LAUNCH-READINESS-VISUAL-RECAP-PARALLEL-1`
(verdict `LAUNCH_READINESS_VISUAL_RECAP_PARTIAL` — could not reach visual PASS because the board
was unavailable in-session).

**No production deployment. No candidate promotion. No Telegram send. Story Continuity production
shadow observation untouched** (no worker restart/rebuild/deploy, no prod `.env`/flag/DB change;
isolated worktree only).

---

## A. Exact board used

`docs/founder_telegram_board.png` — 1024×1280 RGB, provided by the Founder for this phase.
A single NINJA PULSE Telegram-channel mockup ("NINJA PULSE · 126 746 подписчиков"): two phone
columns of example posts (NEWS, BREAKING, DATA, QUOTE, a pinned media group), a numbered
right-hand legend, an "ЭЛЕМЕНТЫ СТИЛЯ" key, a "Telegram-функции которые используем" checklist,
and a footer ("Единый стиль. Разные форматы. Всегда узнаваемо.").

The superseded proxy (`nnj_editorial_visual_system_master_prototype.png`) was **not** used.

## B. Authority statement

Authority order applied, exactly as instructed:

1. **`docs/founder_telegram_board.png`** (attached, on disk)
2. explicit Founder decisions in this phase (§3 of the brief — DATA hero-metric, QUOTE composition)
3. accepted factual/media-safety requirements (NUMBER_MISMATCH / INFOGRAPHIC_DESTROYED hard BLOCK)
4. ACTIVE / CANDIDATE VisualSpec
5. previous master/proxy boards
6. current renderer code

Existing renderer code did not override the board: where the board and code conflicted (DATA
generated, QUOTE) the code was changed, and the conflict is reported explicitly below — the board
was not reinterpreted to make current code pass.

## C. Base SHA

`0175dc3b3c0c43a278227ae47a14f0481425ad11` — `docs(launch-readiness): LAUNCH-READINESS-VISUAL-RECAP-PARALLEL-1 audit + local visual/recap canary`
(branch `feature/launch-readiness-visual-recap-parallel-1`, worktree
`C:/Users/Theodor/ai-newsroom-launch-visual-recap-1`).

## D. Final SHA

`a1ce123` (this report + the DATA hero-metric renderer, the QUOTE composition renderer, the
RenderEvidence derivers, the vNEXT CANDIDATE specs, the focused tests, and the Founder contact
sheet. See `git log` on the branch (this is a doc-only `--amend` after the SHA fill-in; the branch
HEAD is authoritative).

## E. Board semantic extraction

### NEWS (legend 1: "Категория, время, заголовок. Фото с лёгким фирменным водяным знаком. Кнопки: источник и подписка.")
- **Hierarchy:** `● PULSE / <CATEGORY>` + time → bold uppercase headline **above** the media →
  media → concise body → optional highlighted quote block → `NP-xxxx` + `Источник: <publisher>` →
  reactions → views/time → `[🔗 Источник]` + `[NNJ NINJA PULSE]` buttons + share.
- **Media treatment:** the real source photo, preserved; a **light branded watermark** (the NNJ
  mark, low-contrast) sits on the photo. No heavy frame, no band.
- **Red usage:** restrained — the `●` category dot, the pulse motif, the brand mark.
- **Typography:** bold condensed uppercase headline; regular body; small metadata.
- **Pulse treatment:** subtle; the recurring red ECG motif.
- **Branding:** exactly one NNJ mark on the media.

### BREAKING (legend 2: "Красная плашка выделяет важную новость. Крупный заголовок, акцентное фото и красные элементы.")
- **Hierarchy:** identical to NEWS, but the category row reads `● BREAKING` (red) and selected
  headline words are red ("НОВЫЙ **IPHONE 17**").
- **Media treatment:** dramatic/dark source photo, preserved; a **red pulse line crosses the
  lower part of the media**; the light NNJ watermark.
- **Red usage:** stronger — red `BREAKING` marker, red headline emphasis, red pulse over media.
- **Retired and still forbidden:** giant lower-third, large dark bottom banner, oversized baked
  `BREAKING` wordmark, heavy old frame.
- **Branding:** one NNJ mark.

### DATA (legend 3: "Инфографика с цифрами. Фирменный стиль: чёрный фон, красный акцент, линейный импульс, техническая сетка.")
- **Hierarchy:** dominant primary number → unit → smaller label → grey secondary description →
  red delta pill → trend line. `NP-xxxx` / `Источник` / reactions / buttons below, Telegram-native.
- **Media treatment (GENERATED):** a **generated dark-graphite panel** — "500" (large white) /
  "МЛН" (large red) / "ПОЛЬЗОВАТЕЛЕЙ" (white, smaller); "Достиг ChatGPT в июле 2025 года" (grey);
  a **red line chart** ending in a white dot; a **red-outlined "+38%" pill** + "рост за 2 месяца"
  (grey); a subtle **technical grid**.
- **Red usage:** the unit, the chart, the delta-pill outline, the pulse motif.
- **Typography:** very large condensed primary number; red unit; small tracked label; grey secondary.
- **Pulse treatment:** the chart line **is** the "линейный импульс"; a short red pulse motif otherwise.
- **Branding:** one NNJ mark.

### QUOTE (legend 4: "Сильная цитата оформлена отдельным блоком с фото автора.")
- **Hierarchy:** large **red quote-mark glyph** → dominant quote body (left ~60%) → author name
  (red) → author role/title (smaller grey). `NP-xxxx` / views / time / buttons below, Telegram-native.
- **Media treatment:** black/graphite composition; the **author portrait on the supporting
  right-hand strip** (~40% width, full height); dark left ground for the text.
- **Red usage:** the quote-mark glyph, the author name, the brand mark.
- **Typography:** large white quote body; red author name; smaller grey role line.
- **Pulse treatment:** none inside the quote card.
- **Branding:** one NNJ mark.

## F. Telegram-native vs media-rendered responsibilities

The board's own checklist ("Telegram-функции которые используем") is explicit. Split:

| element | owner |
|---|---|
| `● PULSE / <category>` + time (top row) | **Telegram-native** — caption text with `show_caption_above_media` |
| headline (bold, above media) | **Telegram-native** — caption |
| body / caption text | **Telegram-native** — caption |
| highlighted quote block (`💬` + `<blockquote>` + `— author`) | **Telegram-native** — "Цитаты и выделения" |
| `NP-xxxx` editorial code | **Telegram-native** — caption line |
| `Источник: <publisher>` | **Telegram-native** — caption line |
| 🔥 👍 ❤️ reactions | **Telegram-native platform state** — never faked in media |
| 👁 views + time | **Telegram-native platform state** — never faked in media |
| `[🔗 Источник]` / `[NNJ NINJA PULSE]` buttons + share | **Telegram-native** — inline keyboard |
| media groups / albums | **Telegram-native** — media group |
| source photo + light NNJ watermark (NEWS/BREAKING) | **media-rendered** — `apply_master_news_branding` |
| red pulse line over lower media (BREAKING) | **media-rendered** |
| the DATA hero-metric panel (number, unit, label, secondary, chart, delta pill, grid) | **media-rendered** — `render_data_hero_card` |
| the QUOTE composition (red quote glyph, quote body, portrait, author name, role) | **media-rendered** — `render_quote_card` |
| exactly one NNJ mark per branded media image | **media-rendered** |

The renderers bake **only** the media-rendered rows. The `PULSE / QUOTE` label and the `NP-xxxx`
code, which the previous QUOTE renderer baked, are now removed — the board renders them natively.

## G. Board / current matrix

| Format | Board | Current renderer (pre-phase) | Match? | Action taken |
|---|---|---|---|---|
| NEWS | photo + light NNJ watermark; hierarchy native; one mark | `apply_master_news_branding` — photo preserved + one fused lower signature (line+pulse+one mark), adaptive safe corner; native card `render_v81_news_card_html` | **YES** | none (phase §8 — do not reimplement) |
| BREAKING | NEWS family; red `BREAKING` marker + red headline words (native); red pulse over lower media; **no band/wordmark** | `render_breaking_frame` — native-size source + the MASTER NEWS fused signature; band/wordmark retired | **YES (structure)** | none. Note: red headline emphasis is Telegram-native (Telegram has no colored message text) — see §T. |
| DATA — existing infographic | source-preserving; no second competing metric | `render_data_card` MINIMAL_SOURCE_PRESERVING — source kept, stat block skipped, hard guards | **YES** | none — explicitly **not** converted to a hero card (phase §3) |
| DATA — generated | **hero metric** — big number/unit/label, grey secondary, red chart, delta pill, grid, graphite | compact ~30 %-width corner stat on a photo (retired V2.20) | **NO — STRUCTURAL DRIFT** | **implemented** `render_data_hero_card` (§K) + `telegram_data` vNEXT CANDIDATE (§M) |
| QUOTE | large red quote-mark motif; author name red; **author role** grey; portrait right; `PULSE`/`NP` native | typographic `"…"` white; `— speaker` red; **no role**; baked `PULSE / QUOTE` + `NP-xxxx` | **NO — STRUCTURAL DRIFT** | **implemented** the board composition in `render_quote_card` (§L) + `telegram_quote` vNEXT CANDIDATE (§M) |
| Global brand | black/graphite/white/NNJ red `#ED1C24`; recurring pulse; one mark per image | palette from `nnj_logo_red.svg`; pulse in every format; single-mark invariant enforced structurally + Art Director hard BLOCK | **YES** | none |

Per-format board match verdicts (phase §5):

```
NEWS_BOARD_MATCH                        = PASS
BREAKING_BOARD_MATCH                    = PASS
DATA_EXISTING_INFOGRAPHIC_BOARD_MATCH   = PASS
DATA_GENERATED_BOARD_MATCH             = PASS   (after this phase's hero-metric renderer)
QUOTE_BOARD_MATCH                      = PASS   (after this phase's composition change)
```

## H. NEWS result

**Unchanged — board-compatible, no code touched.** Canary `news_current`: `logo_count=1`,
`scrim_treatment=none`, `source_image_treatment` preserve/crop. On a busy bright photo the
adaptive scorer places the (single) mark `upper_right` → soft `SPEC_LOGO_ZONE_MISMATCH` vs the
ACTIVE `telegram_news` v2 `logo_zone=lower_right` → **REWORK (soft, never hard)** — the same
adaptive-corner-vs-fixed-zone tension already recorded in the prior phase, not a regression and
not a launch blocker. `test_founder_visual_board_alignment_1.py::test_news_render_evidence_unchanged_*`
+ the full `test_v2_10h_master_news_production.py` suite pass.

## I. BREAKING result

**Unchanged — board-compatible, no code touched.** `render_breaking_frame` still composites the
native-size source + the MASTER NEWS fused signature; the retired band/wordmark/rule stay gone
(`derive_breaking_render_evidence` → `renderer_version="pulse-breaking-v2"`, `scrim_treatment=none`,
`placement_zone` NOT_MEASURED). Canary `breaking_current`: one mark, no band. The board's **red
headline emphasis** ("НОВЫЙ IPHONE 17") is Telegram caption formatting — Telegram messages have no
colored text, so this is rendered as bold native text, not baked into the image — flagged for
Founder confirmation in §T.

## J. DATA — existing-infographic result

**Unchanged — board-compliant.** `EXISTING_INFOGRAPHIC` → `MINIMAL_SOURCE_PRESERVING`: the source
infographic is kept and only the bottom pulse+NNJ signature is added; the stat block is skipped
entirely ("42 stays 42"). Canary `data_existing_infographic`: `actual_line_count=0`. Hard guards
verified: `NUMBER_MISMATCH` → BLOCK and `EXISTING_INFOGRAPHIC` + a non-source-preserving mode →
`INFOGRAPHIC_DESTROYED` → BLOCK (`test_design_spec_enforcement.py`, `test_art_director_number_mismatch_blocks.py`).
New test `test_existing_infographic_is_never_converted_to_a_hero_card` pins that MINIMAL never
delegates to the hero renderer.

## K. DATA — generated result

**Implemented.** New `services/brand_renderer.py::render_data_hero_card()` (board format 3):

- a generated **dark-graphite** panel (1280×720), subtle technical grid;
- `data_candidate.value` — dominant primary number, white, deterministically font-fitted in
  `[88, 200]` (drawn **verbatim** — never reformatted/recomputed);
- `data_candidate.unit` — directly beneath, **NNJ red**, uppercased, font-fitted (skipped if empty);
- `data_candidate.label` — smaller white line, wrapped to ≤ 2 lines, no clipping;
- `data_candidate.evidence_fact` — grey secondary line, drawn **verbatim**, wrapped ≤ 3 lines;
- `data_candidate.delta` — an optional red-outlined pill (drawn only when supplied);
- `data_candidate.series` — an optional red trend line **plotted verbatim** from the supplied
  points (min-max normalised, linear x), white end-dot — drawn only when ≥ 2 points are supplied;
  never a synthetic/interpolated series;
- a short red pulse motif; **exactly one** canonical NNJ mark, lower-right, inside the safe margin.

`DataCandidate` gained two optional fields with defaults (`series: tuple[float, ...] = ()`,
`delta: str | None = None`) — every existing construction site is byte-identical.
`render_data_card(presentation_mode=FULL_DATA_CARD)` now delegates to `render_data_hero_card()`;
`MINIMAL_SOURCE_PRESERVING` / `NO_OVERLAY_SAFETY` are untouched. The retired V2.20 compact-corner
helpers (`_select_data_block_placement`, `_measure_data_stat_block`, the adaptive backing) are
kept for their unit coverage but are no longer reached from any production dispatch.

Canary `data_generated_hero`: `logo_count=1`, `logo_zone=lower_right`, `primary_font_size=200`,
`actual_line_count=1`; against the ACTIVE v1 spec → soft REWORK (font 200 > 88 — the stale v1
range); against the `telegram_data` **vNEXT CANDIDATE** → **PASS_WITH_NOTES**, zero hard failures.

## L. QUOTE result

**Implemented.** `render_quote_card()` rewritten to the board composition (format 4):

- large **red quote-mark glyph** (`“`, `_font(132)`), positioned as the opening mark of the block;
- dominant white quote body — `quote_candidate.text` **verbatim**, deterministically font-fitted
  (`_fit_wrapped_block`, `[28, 44]`, ≤ 6 lines) — never paraphrased, never mid-word clipped;
- the author portrait on the supporting right strip (own aspect, no crop) with the dark left
  ground and the pinned 40 px feather (unchanged — the "not a source scrim" contract holds);
- `quote_candidate.speaker` — **NNJ red** (no `— ` prefix);
- `quote_candidate.role` (new optional field) — smaller neutral grey, **only when supplied**; a
  missing role is **never fabricated**, the layout simply omits the line;
- **removed**: the baked `PULSE / {category}` label and the baked `NP-xxxx` editorial code (the
  board renders both Telegram-natively); `category`/`editorial_code` still accepted for dispatch
  symmetry, never drawn;
- exactly one canonical NNJ mark, lower-right (`_paste_svg_mark`), card 1200×675, margin 64
  (RenderEvidence parity constants unchanged).

Canaries `quote_final` (portrait + full role) and `quote_fallback_missing_role`: `logo_count=1`,
`logo_zone=lower_right`, `merged=pass_with_notes`, deterministic, no clipping.

## M. Candidate spec changes

Created via the canonical registry lifecycle (`create_candidate_spec()`), **never promoted**, in
the **dev control-plane DB only** (production untouched). Proposal doc:
`design/proposed_telegram_data_quote_vnext_candidates.md`; idempotent applier:
`scripts/propose_visual_spec_vnext_candidates.py`.

| scope | new row | parameters | note |
|---|---|---|---|
| `telegram_data` | **v2 CANDIDATE** (`id 10e47a85…`) | `font_size_max 200, font_size_min 88, max_line_count 2, safe_margin_frac 0.019, logo_zone lower_right, scrim_treatment none, placement_zone upper_left` | hero-metric font range; `source_image_treatment` dropped (generated card, no source photo) |
| `telegram_quote` | **v2 CANDIDATE** (`id 4dda4da6…`) | byte-identical to v1 | composition change only; recorded in `notes` (no `DeclarativeVisualParameters` field expresses quote-mark motif / author role) |

`telegram_data` v1 and `telegram_quote` v1 remain **ACTIVE**. `telegram_news` v2 / `telegram_breaking`
v2 remain ACTIVE and unchanged. `AUTO_PROMOTION=false`; Founder promotion is a separate phase.

## N. RenderEvidence

`services/render_evidence.py`:

- new `_derive_data_hero_evidence()` — for `FULL_DATA_CARD`, replays the hero renderer's own two
  deterministic decisions (fitted primary-value font size; wrapped label line count) and reads
  back its locked constants. Reports: `renderer_variant="brand_renderer.render_data_hero_card"`,
  `renderer_version="pulse-data-hero-v1"`, canvas 1280×720, `safe_margin_frac=0.05625`,
  `logo_count=1`, `logo_zone="lower_right"`, `placement_zone="upper_left"`, `scrim_treatment="none"`,
  `presentation_mode="full_data_card"`, `primary_font_size` (fitted), `actual_line_count` (label
  lines), `text_clipped=False`. `source_image_treatment` / `source_preserved` are `NOT_MEASURED`
  **and** in `not_applicable_fields` (a generated artifact, not a source transform — distinct from
  a measurement gap), with a forensic note.
- `MINIMAL_SOURCE_PRESERVING` / `NO_OVERLAY_SAFETY` evidence unchanged.
- QUOTE evidence unchanged (card geometry / margin / one-mark / "not a source scrim" note all
  identical); the renderer no longer bakes the `PULSE`/`NP` metadata, so nothing new to expose.

`test_render_evidence_parity.py` updated in lock-step (the FULL-DATA parity test now replays the
hero renderer's decisions; the busy-photo-scrim test retargeted to the source-preserving path).

## O. Art Director result

Unchanged mechanism — `services/telegram_art_director_spec_evaluation.py` merge logic and §19
hard-failure precedence are untouched. Verified for the new renders:

- DATA: `NUMBER_MISMATCH` → hard BLOCK; `EXISTING_INFOGRAPHIC` + non-preserving mode →
  `INFOGRAPHIC_DESTROYED` hard BLOCK; hero card `logo_count>1` would be a hard BLOCK (evidence
  reports exactly 1); a clipped metric would set `text_clipped` (evidence reports `False`).
- QUOTE: `TEXT_CLIPPING` → hard BLOCK; `DUPLICATE_NNJ_BRAND_MARK` → hard BLOCK; a missing portrait
  is a graceful layout, not a failure.
- No accepted render in the canary reaches BLOCK; the only non-PASS results are soft REWORKs from
  the stale ACTIVE `telegram_data` v1 font range and the adaptive logo-zone on busy photos — both
  resolved by promoting the vNEXT candidates (§T), neither a launch blocker.

## P. Canary paths

- `scripts/_founder_visual_board_alignment_canary.py` — LOCAL only, no Telegram send, no DB writes
  (specs read read-only). **CANARY PASS.**
- `artifacts/founder_visual_board_alignment_1/` — `news_current.png`, `breaking_current.png`,
  `data_existing_infographic.png`, `data_generated_hero.png`, `quote_final.png`,
  `quote_fallback_missing_role.png`, `canary_records.json`, `CONTACT_SHEET.png`.

| canary | logo | zone | scrim | font | SPEC | Art merged |
|---|---|---|---|---|---|---|
| news_current | 1 | upper_right (adaptive) | none | — | rework (soft zone) | rework |
| breaking_current | 1 | upper_right (adaptive) | none | — | rework (soft zone) | rework |
| data_existing_infographic (MINIMAL) | 1 | lower_right | none | — | rework (soft zone) | rework |
| data_generated_hero (FULL → hero) | 1 | lower_right | none | 200 | vs v1 ACTIVE: rework · **vs vNEXT CANDIDATE: pass_with_notes** | pass_with_notes |
| quote_final (portrait + role) | 1 | lower_right | n/a | — | pass_with_notes | pass_with_notes |
| quote_fallback_missing_role | 1 | lower_right | n/a | — | pass_with_notes | pass_with_notes |

Invariants held: exactly one NNJ mark per render; BREAKING band retired (`scrim=none`);
existing-infographic number preserved (`lines=0`); the hero card conforms to the vNEXT candidate
spec; QUOTE role + missing-role fallback both render deterministically; **no BLOCK on any accepted
render**.

## Q. Contact sheet

`artifacts/founder_visual_board_alignment_1/CONTACT_SHEET.png` — the **FOUNDER BOARD REFERENCE**
(`docs/founder_telegram_board.png`, labelled VISUAL AUTHORITY #1) across the top, then the six
CURRENT / FINAL renders (NEWS, BREAKING, DATA existing-infographic, **DATA generated hero metric**,
**QUOTE final**, **QUOTE missing-role fallback**), each captioned with
`logo / zone / scrim / font / art-decision`. One file, easy to compare against the board.

## R. Tests

Focused (`tests/test_founder_visual_board_alignment_1.py`, 15 tests) + updated in-scope suites,
`-p no:randomly`:

```
tests/test_founder_visual_board_alignment_1.py .................................. 15 passed
tests/test_brand_renderer.py + test_render_evidence_parity.py + test_design_spec_enforcement.py
    ...................................................................  123 passed
full relevant sweep (visual + spec + evidence + art-director + recap + quote-integration + v2_10h
    + presentation-director + news-telegram-presentation)  ..............  509 passed, 4 skipped
```

Covered per §14: generated DATA hero metric; metric drawn verbatim (never invented); graph only
from a supplied series; value font fitting `[88, 200]`; label ≤ 2 lines, no clipping; existing
infographic preserved; NUMBER_MISMATCH block; INFOGRAPHIC_DESTROYED block; QUOTE composition;
author role drawn when supplied; missing-role fallback (never fabricated); QUOTE body font-fit /
no clipping; one NNJ mark (all formats); NEWS parity; BREAKING parity; RenderEvidence parity;
Art Director merge.

- **PASSED:** 509 (sweep) incl. the 15 new focused tests
- **SKIPPED:** 4
- **NEW_FAILURES: 0** ✅ (acceptance met)
- **KNOWN_FAILURES (pre-existing on base `0175dc3`, reproduced on a pristine checkout, unrelated
  to visual rendering — this phase touched none of the code they exercise):**
  - `tests/test_recap_story_integrity.py` — `test_case_b_accurate_generic_opener_fails_integrity`,
    `test_case_d_arxiv_large_language_models_generic_opener_fails_integrity`,
    `test_large_language_models_nine_member_lucky_pair_stress_case_still_fails`,
    `test_recent_generic_opener_with_near_duplicate_fails_integrity`,
    `test_autonomous_generic_opener_fails_integrity` (each still asserts `eligible is False`
    correctly — only the `pair_entity_exclusions` diagnostic dict is empty; safety intact);
  - `tests/test_presentation_director_mode_contract.py::test_enforce_gate_actually_assigns_every_mutating_target_at_least_once`
    (an AST-parse guard on `worker/content_cycle.py`, untouched this phase).

## S. Static checks

- `services/` (repo-normal mypy scope): `brand_renderer.py`, `render_evidence.py`,
  `presentation_director.py`, `telegram_art_director_spec_evaluation.py` → **mypy: Success, no
  issues**.
- `ruff check` on every changed + new file → **All checks passed** (5 `F401` introduced in
  `test_render_evidence_parity.py` by the parity-test rewrite were removed).
- `ruff format`: the new files are formatted; the pre-existing `services/*.py` files were already
  not `ruff format`-clean at base (the repo has no `[tool.ruff]` config and does not enforce it),
  so they were left as-is — no NEW format drift introduced by this phase's edits.
- Line endings: `brand_renderer.py` / `test_design_spec_enforcement.py` were normalised back to LF
  to match the repo (the Windows editor had flipped them to CRLF); the committed diff is the
  semantic change only.
- **NEW_STATIC_ERRORS: 0** ✅

## T. Remaining Founder decisions

1. **Promote the vNEXT CANDIDATE specs** — `telegram_data` v2 (hero-metric font range,
   `source_image_treatment` dropped, `placement_zone=upper_left`) and `telegram_quote` v2
   (composition-only) — a separate, explicitly-authorized promotion phase. Until then the ACTIVE
   `telegram_data` v1 font range makes the hero card read as a **soft REWORK** in SPEC_MATCH (not
   a block).
2. **Production control-plane DB is still on `telegram_news`/`telegram_breaking` v1** (v2 is dev
   only, per the prior phase). The `telegram_data`/`telegram_quote` v2 candidates were also
   created **dev only**. A later deploy-gated phase replays the promotions against production.
3. **BREAKING red headline emphasis** — the board shows red words in the headline; Telegram
   message text cannot be coloured. Confirm the intended behaviour: bold native text (current), or
   bake the headline into the BREAKING media as an overlay (a new renderer change, out of scope
   here).
4. **Adaptive logo zone vs fixed spec `logo_zone`** — on busy photos the (single) NNJ mark lands
   `upper_right` / `lower_left` instead of `lower_right`, a soft `SPEC_LOGO_ZONE_MISMATCH`.
   Confirm whether the spec's `logo_zone` is a hard anchor or a documented "preferred, adaptive"
   preference (recommended: the latter — the mark is always present exactly once).
5. **Recap visual** — unchanged this phase; the two historical recap mockups remain
   `NEEDS_FOUNDER_REVIEW` (carried from the prior phase, not re-litigated).

## U. Recommended production rollout

1. **`VISUAL-SPEC-VNEXT-PROMOTION`** (deploy-gated, explicitly authorized) — Founder reviews the
   two `docs/founder_telegram_board.png`-aligned candidate specs, then `promote_candidate()` runs
   for `telegram_data` v2 + `telegram_quote` v2 (and the earlier `telegram_news`/`telegram_breaking`
   v2) against the **production** control-plane DB. No renderer change.
2. **Shadow canary on production ingest** — with the promoted specs, run the Art Director in
   shadow over real DATA/QUOTE decisions for a bounded window; confirm zero hard failures and the
   expected SPEC_MATCH PASS on the hero card and the new QUOTE composition.
3. **Wire `DataCandidate.series` / `.delta` and `QuoteCandidate.role` from the pipeline** — the
   renderer accepts them today; `services/presentation_director.py`'s extractors still pass only
   the base fields, so the hero chart / delta pill and the QUOTE role line are dormant until a
   small, separately-scoped extraction change populates them from trusted structured data.
4. Only then: an Art Director **enforcing-veto** phase.

---

## Final verdict

The real Founder board is now the authority. NEWS / BREAKING remain board-compatible and
untouched. DATA existing-infographic is board-compliant and its fact-safety guards
(NUMBER_MISMATCH, INFOGRAPHIC_DESTROYED) hard-BLOCK. The two Founder-decided drifts are
implemented: **DATA generated is now the hero-metric card** and **QUOTE is the board composition**
(red quote-mark motif, author name in red, author role in grey, no baked native metadata). The
single-NNJ invariant holds on every render; no factual visual corruption; Telegram-native
responsibilities are clean; **NEW_FAILURES = 0**, **NEW_STATIC_ERRORS = 0**; no production
mutation, no candidate promotion, no deploy.

The only open items are Founder **promotion** decisions (§T) — a soft SPEC_MATCH REWORK against
the deliberately-not-yet-promoted candidate specs is not a visual defect.

**FOUNDER_VISUAL_BOARD_ALIGNMENT_PARTIAL**

Do not deploy. Wait for Founder review and candidate-spec promotion.
