# LAUNCH-READINESS-VISUAL-RECAP-PARALLEL-1 — report

Second parallel launch-readiness workstream. Telegram visual system (NEWS / BREAKING / DATA /
QUOTE) + Art Director / VisualSpec enforcement + Event Recap readiness. **No production
deployment. No Story Continuity / suppression / clustering changes. No public publication.**

Runs beside the live `STORY-CONTINUITY-P0.1-ARXIV-COVERAGE-SHADOW-1` observation
(prod `automation_worker` = `c6694b9`, shadow, suppression OFF) — that observation was not
touched: no worker restart/rebuild/deploy, no prod `.env`/flag/DB mutation, isolated worktree.

---

## A. Worktree / recovery result

`git worktree list` enumerated 17 worktrees. Branches/worktrees inspected for
visual/renderer/design-spec/art-director/recap/media work; dirty & untracked state preserved
(nothing reset/cleaned/deleted).

**`VISUAL_RECONCILIATION_EXISTING_STATE = COMPLETE`.**

`VISUAL-RENDERER-RECONCILIATION-1` already landed and was **Founder-approved**, on the same
lineage this phase builds on:

| commit | what |
|---|---|
| `fd4e006` | NEWS/BREAKING v2 spec proposal + `assets/brand/newsroom_visuals/vrr1_reconciliation/*.png` comparison artifacts (§3/§12/§14) |
| `ff458ae` `577467d`… `d016764` | BREAKING 22%-dark-band + baked "BREAKING" wordmark + red accent rule **RETIRED** → NEWS family; RenderEvidence + tests updated |
| `1e8781e` `9902194` `7bc9435` | `RenderEvidence` contract + Art Director **field-by-field** ACTIVE-spec enforcement |
| `5bb04e4` | DATA source classification (`EXISTING_INFOGRAPHIC` → `MINIMAL_SOURCE_PRESERVING`) |
| `d2dea2c` | **"Founder decision: APPROVE `telegram_news` v2 + `telegram_breaking` v2"** — only semantic change vs v1 = drop wrongly-derived `placement_zone=lower_left` |

No unfinished reconciliation work needed recovery/continuation. This phase is therefore
**verification + Recap audit + local canaries**, not a re-implementation.

Isolated worktree created for this phase:
`C:/Users/Theodor/ai-newsroom-launch-visual-recap-1`,
branch `feature/launch-readiness-visual-recap-parallel-1`.

## B. Base SHA

`c6694b92674d9280bd61b4061162ff808d422fca` — `docs(story-continuity): STORY-CONTINUITY-P0.1 report`
(the commit prod `automation_worker` runs in shadow; contains the full visual-reconciliation
stack + `d2dea2c`).

## C. Final SHA

`2882b8b` (this report + the local canary script; **zero tracked source files
changed** in the audit).

## D. Founder visual authority statement

Authority order for this phase, as instructed:

1. **The Founder-approved 4-format Telegram visual board** (NEWS / BREAKING / DATA / QUOTE).
2. later explicit Founder corrections
3. accepted production requirements
4. ACTIVE VisualSpec
5. existing renderer implementation

**Board handling caveat (must be resolved by the Founder before a PASS is possible).**
The board image was named as authority #1 but **did not arrive in the session** (text only, on
two attempts). The audit was run against the best in-repo proxy:
`assets/brand/newsroom_visuals/v1/references/nnj_editorial_visual_system_master_prototype.png`
— a 5-format (NEWS/BREAKING/DATA/QUOTE/RECAP) desktop+mobile "ПРОТОТИПЫ ПОСТОВ ДЛЯ TELEGRAM
КАНАЛА" board whose stated common elements (Black/White/NNJ Red, original NNJ logo,
Источник / «NINJA PULSE. Подписаться 🥷» buttons, `NP-XXXX` event code, native Telegram
media/text/buttons/quotes/albums) match the written brief point-for-point — plus
`design/proposed_telegram_news_breaking_v2_candidates.md` and the `vrr1_reconciliation/*.png`
comparisons. **The Founder must confirm this proxy IS the intended board.** Until then the
visual verdict is capped at PARTIAL.

Key structural reading of the board, carried through the whole audit: **the editorial hierarchy
(category marker, headline, body, highlighted quote, reactions, views/time, `NP-xxxx`, Источник
/ Подписаться) is NATIVE Telegram** (caption markup + inline keyboard). The image renderer adds
only: the preserved source photo + a fused lower-right pulse-line-then-`nnj` signature (one
canonical mark). DATA additionally bakes a metric (generated mode only); QUOTE is a designed
composition. This matches the phase's §7 "do not bake all Telegram UI text into the image".

## E. Board-vs-renderer matrix

Live render paths traced (no code changed before documenting):

| Format | Entry point | Renderer | Source treatment | Text overlays | Logo | Pulse | Scrim/band | Final dims | RenderEvidence deriver | Active spec |
|---|---|---|---|---|---|---|---|---|---|---|
| NEWS | `worker/content_cycle.py` → `apply_master_news_branding()` | `services/nnj_master_news_overlay.py` | fit to 1280×720 (`_fit_photo_to_canvas`, center-crop-to-fill) | none baked | 1 canonical mark, `select_master_news_branding()` mutual-exclusion (upper XOR lower) | fused into the single lower signature | none | 1280×720 | `derive_master_news_render_evidence` | `telegram_news` **v2** |
| BREAKING | `content_cycle.py` → `render_branded_media(BREAKING)` → `render_breaking_frame()` | `services/brand_renderer.py` + `select_master_news_branding()` | **native size, preserve** (no fit/crop) | none baked (`category`/`code` accepted, never drawn) | 1 canonical mark (same MASTER NEWS signature) | fused lower signature | **none** (band/wordmark/rule retired) | source dims | `derive_breaking_render_evidence` | `telegram_breaking` **v2** |
| DATA | `content_cycle.py` → `render_branded_media(DATA)` → `render_data_card()` | `services/brand_renderer.py` | fit to 1280×720 | `MINIMAL_SOURCE_PRESERVING`: **none**; `FULL_DATA_CARD`: one compact ~30%-width stat block (value+unit fused + ≤2-line descriptor) | 1 mark, adaptive bottom-only signature (`_select_data_signature`, 4-tier degrade) + guaranteed fallback on scrim | bottom-only pulse+mark, adaptive red/white | none (or a text-tight translucent backing only when a safe corner is too low-contrast) | 1280×720 | `derive_data_render_evidence` | `telegram_data` **v1** |
| QUOTE | `content_cycle.py` → `render_branded_media(QUOTE)` → `render_quote_card()` | `services/brand_renderer.py` | portrait resized to card height at own aspect, pasted right; **no crop** | `"PULSE / {category}"` (red), the quote (white `_font(42)`, verbatim), `"— {speaker}"` (red), `editorial_code` (white) — **all baked** | 1 SVG mark, bottom-right (`_paste_svg_mark`) | none | dark left text panel on the card's own black ground (40px feather over the portrait — not a source scrim) | 1200×675 | `derive_quote_render_evidence` | `telegram_quote` **v1** |
| RECAP (fallback) | `services/event_recap_processor.py` → `render_branded_fallback_media()` → `build_recap_fallback_background()` | `services/brand_renderer.py` | plain 1280×720 black + subject label | subject + optional category | **0** by contract (branding added once later by `apply_master_news_branding()` at Final Post Review + publish) | none | none | 1280×720 | — | — |

Matrix vs the board proxy:

| Format | Founder board (proxy) | Current renderer | Match? | Severity |
|---|---|---|---|---|
| NEWS image | photo preserved; thin red pulse/ECG line along the bottom terminating at one lower-right `nnj`; no scrim; hierarchy native | as above | **YES** | COSMETIC — adaptive scorer can move the mark off `lower_right` on a busy photo (still exactly one) |
| BREAKING image | NEWS family; urgency via red `● BREAKING` marker + red headline words (native text); pulse may cross lower media | image identical to NEWS family; band/baked-text retired; urgency entirely in native text | **YES (structure)** | COSMETIC — "stronger urgency in the image itself" is only partially expressed. Founder note. |
| DATA — existing infographic | source-preserving; no second competing metric | `MINIMAL_SOURCE_PRESERVING`: stat block skipped entirely; classifier auto-selects it for `EXISTING_INFOGRAPHIC` | **YES** | — (hard guards verified, §L) |
| DATA — generated | **hero metric** (very large primary number, secondary delta, red chart, technical grid, black/red/white) | **compact ~30%-width corner stat block** on the preserved/cropped photo; Phase V2.20 explicitly **retired** the "giant isolated number / full-frame dark card" | **PARTIAL / DRIFT** | **STRUCTURAL — NEEDS_FOUNDER_DECISION.** A deliberate past decision (V2.20) that may predate / conflict with this board. |
| QUOTE | large **red quotation-mark motif**; dominant quote; portrait secondary; **author name red**; **role/title smaller**; `NP-xxxx` native | typographic `"…"` in white; `— speaker` red; **no** red quote-mark glyph; **no** role/title line (`QuoteCandidate` = text+speaker only); `PULSE / QUOTE` label + `NP-xxxx` **baked into the image** | **PARTIAL / DRIFT** | **STRUCTURAL/COSMETIC — NEEDS_FOUNDER_DECISION.** |
| RECAP | full editorial card in the same PULSE system (headline, "ВСЁ ЗА 3 МИНУТЫ", media, album) | Tiers 1/2B: real Story media + MASTER NEWS branding; Tier 3: plain unbranded background (mark applied once later) | **PARTIAL** | Founder note — two unresolved recap mockups remain NEEDS_FOUNDER_REVIEW (§19). Not re-litigated. |
| Global brand | black/graphite/white/NNJ red `#ED1C24`; recurring pulse motif; exactly ONE canonical `nnj` per image | palette extracted from `nnj_logo_red.svg` fill; pulse in every format; single-mark enforced structurally (`select_master_news_branding` XOR) + Art Director `DUPLICATE_NNJ_BRAND_MARK` hard-BLOCK | **YES** | — |

Classification of drifts: DATA-generated = **STRUCTURAL**; QUOTE motif/role = **STRUCTURAL**;
QUOTE baked `NP`/label + BREAKING image-urgency = **COSMETIC**. None is a FACT_SAFETY drift.
None was silently "reinterpreted to make current code pass" — each is reported as an explicit
Founder-visible conflict.

## F. NEWS result

**READY.** Live path is `apply_master_news_branding()` (not the dead `render_news_hero()`, which
is reachable only as a degraded fallback if a DATA/QUOTE/BREAKING render throws). Native card is
`render_v81_news_card_html()` (headline bold + one body paragraph + optional non-expandable quote
blockquote; `[🔗 Источник]` is a separate inline keyboard). Canaries `news_01_dark_photo`,
`news_02_light_photo`: `logo_count=1`, `logo_zone=lower_right`, `scrim=none`,
`source_image_treatment=preserve`, SPEC_MATCH **PASS** on v2, Art Director merged **pass**. No
change required.

## G. BREAKING result

**READY** (structure); one Founder note. `render_breaking_frame()` composites the native-size
source + the exact MASTER NEWS fused signature; the retired band/wordmark/rule are gone
(`derive_breaking_render_evidence` → `renderer_version="pulse-breaking-v2"`, `scrim_treatment=none`,
`source_image_treatment=preserve`). Canary `breaking_04_light_photo`: merged **pass_with_notes**.
Canary `breaking_03_dark_dramatic` (busy iPhone hero photo): mark placed `upper_right` by the
adaptive safe-corner scorer → soft `SPEC_LOGO_ZONE_MISMATCH` vs the spec's `logo_zone=lower_right`
→ **REWORK** (soft, never hard; still exactly one mark). Founder note: confirm the board reading
is "BREAKING urgency lives in native text, image identical to NEWS" (the reconciliation
conclusion), and confirm whether `logo_zone` should stay a soft preference (adaptive) or become a
hard anchor.

## H. DATA result

**Existing-infographic path: READY.** `MINIMAL_SOURCE_PRESERVING` skips the stat block entirely
(canary `data_05_existing_infographic`: `actual_line_count=0`, merged **pass_with_notes**) — the
source's own printed metric is never redrawn or overpainted. `NUMBER_MISMATCH` and
`INFOGRAPHIC_DESTROYED` are both **hard BLOCK** (verified §L, canary
`data_05b_infographic_full_card_DESTROY_TEST` → merged **block**, `hard_failures=['INFOGRAPHIC_DESTROYED']`).

**Generated-card path: NEEDS_FOUNDER_DECISION.** The renderer produces a restrained compact
corner stat block; the board shows a hero-metric infographic layout. Canary
`data_06_generated_card` also shows `source_image_treatment=crop` (a non-16:9 source
center-cropped to the fixed 1280×720 DATA canvas) → soft `SPEC_SOURCE_TREATMENT_MISMATCH`
(mechanical fit, not a recompose → soft REWORK, not hard). If the Founder wants the board's
hero-metric treatment, that is a new candidate spec + renderer work in a **follow-up phase**, not
this one.

## I. QUOTE result

**NEEDS_FOUNDER_DECISION.** Canaries `quote_07_light_portrait` / `quote_08_dark_portrait`:
`logo_count=1`, `logo_zone=lower_right`, merged **pass_with_notes** — structurally safe, single
mark, quote rendered verbatim. Drift vs the board: (1) no large red quotation-mark motif — the
renderer uses plain typographic `"…"` in white; (2) no role/title line — `QuoteCandidate` carries
only `text` + `speaker`; (3) `"PULSE / QUOTE"` label and `NP-0187` are baked into the image where
the board keeps `NP-xxxx` in native text. Fixing (1)–(3) = a candidate `telegram_quote` v2 +
`QuoteCandidate.role` + `render_quote_card()` work in a follow-up phase.

## J. RenderEvidence result

**READY — no rebuild needed.** `services/render_evidence.py` derivers replay the renderer's own
deterministic helpers (`select_master_news_branding`, `_select_data_signature`,
`_measure_data_stat_block`, `_fit_photo_to_canvas`, locked fraction constants) — never an LLM
estimate. `NOT_MEASURED` is a distinct sentinel and is kept explicit (e.g. NEWS/BREAKING
`placement_zone` is `NOT_MEASURED` **and applicable** — a real, Founder-visible measurement gap,
deliberately not folded into `not_applicable_fields`). `not_applicable_fields` is used only where
the renderer positively determined a field does not apply (QUOTE `scrim_treatment` with a pinned
40px-feather forensic note; MINIMAL_SOURCE_PRESERVING `primary_font_size`). Fields exercised in
the canary: `logo_count`, `logo_zone`, `placement_zone`, `scrim_treatment`,
`source_image_treatment`, `source_preserved`, `actual_line_count`, `safe_margin_frac`,
`canvas_width/height`.

## K. VisualSpec result

ACTIVE specs read **read-only** from the **dev control-plane DB** (`ai_newsroom`) — not mutated:

| scope | version | status | parameters |
|---|---|---|---|
| `telegram_news` | v2 | **active** | `safe_margin_frac 0.019, logo_zone lower_right, scrim_treatment none, source_image_treatment preserve` |
| `telegram_breaking` | v2 | **active** | same as news v2 |
| `telegram_data` | v1 | **active** | `font_size 48–88, max_line_count 2, safe_margin_frac 0.019, logo_zone lower_right, scrim none, source preserve` |
| `telegram_quote` | v1 | **active** | `safe_margin_frac 0.019, logo_zone lower_right, scrim none, source preserve` |
| `telegram_news` / `telegram_breaking` | v1 | superseded | (carried `placement_zone=lower_left`) |

- **A. Spec matches board** — `telegram_news` v2 and `telegram_breaking` v2 match the board's NEWS
  image treatment (preserve + one lower-right signature + no scrim). `telegram_data` v1 and
  `telegram_quote` v1 match on margin/logo-zone/scrim/source; `telegram_data`'s `font_size 48–88`
  is consistent with a compact stat block, **not** the board's hero-metric.
- **B. Spec conflicts board** — none of the ACTIVE specs *conflicts* the board; the DATA/QUOTE
  **renderer** drift (§H/§I) is a code-vs-board question, and the specs are simply **incomplete**
  for the board's DATA hero-metric and QUOTE motif (no field expresses either).
- **C. Spec incomplete** — `telegram_data` has no "metric emphasis / hero vs corner" parameter;
  `telegram_quote` has no quote-mark-motif / author-role parameter. **No candidate spec was
  created and nothing was promoted** (§12 / AUTO_PROMOTION=false). Proposed candidate corrections
  are recorded here for Founder review only:
  - `telegram_data` v2 candidate: add an explicit `metric_placement` / emphasis field once the
    Founder decides hero-metric vs corner-accent.
  - `telegram_quote` v2 candidate: add author-role + quote-mark-motif fields once the Founder
    decides the QUOTE composition.
- **Production split-brain (unchanged, flagged):** per `design/proposed_telegram_news_breaking_v2_candidates.md`
  the v2 promotion was applied to the **dev** control-plane DB only; the **production** control-plane
  DB is still on v1. Reconciling it = replay the idempotent `scripts/activate_visual_spec_v2.py`
  against prod in a later **explicitly-authorized** deploy phase. Not this phase.
- **`logo_zone` / `source_image_treatment` enforcement strength:** currently **soft** (REWORK) for
  a zone/fit mismatch, **hard** only for `recompose`-over-`preserve`, `max_line_count` exceeded,
  and `logo_count > 1`. Confirm that soft classification is intended.

## L. Art Director result

**READY (SHADOW ONLY — no visual veto wired anywhere;
`telegram_art_director_shadow_enabled` defaults False).** Three layers:

1. `services/telegram_art_director.py::evaluate_art_direction_shadow` — structural checks only:
   empty bytes → BLOCK; renderer-reported duplicate branding (`degradation_mode="upper_and_lower"`
   or both components placed) → BLOCK/HUMAN_REVIEW; renderer-reported safe degradation
   (`tier="none"` / `placement="omitted"`) → PASS (never a "missing mark" false positive).
2. `services/telegram_art_director_vision.py::evaluate_art_direction_vision` — real Gateway vision
   call over the actual bytes; **fails soft** to `PASS_WITH_NOTES` + `HUMAN_REVIEW` (never a silent
   PASS, never BLOCK on a judgment that wasn't made); deterministic backstop forces
   `NUMBER_MISMATCH` → BLOCK regardless of the model's decision string.
3. `services/telegram_art_director_spec_evaluation.py` — merges the pixel result with
   `RenderEvidence` + the ACTIVE Design Spec + source classification into the §18 multi-dimension
   verdict (FACT_SAFETY, SPEC_MATCH, REFERENCE_MATCH, SOURCE_PRESERVATION, TYPOGRAPHY, LAYOUT,
   BRANDING, VISUAL_QUALITY). **§19 hard failures always yield BLOCK and can never be downgraded
   by an optimistic vision decision** (`merge_spec_evaluation_into_result` §10 precedence):
   - `NUMBER_MISMATCH` (FACT_SAFETY) → BLOCK ✓ (unit test + canary)
   - `EXISTING_INFOGRAPHIC` + non-source-preserving mode → `INFOGRAPHIC_DESTROYED` → BLOCK ✓ (canary `data_05b`)
   - `DUPLICATE_NNJ_BRAND_MARK` (structural or model-drawn) → BLOCK ✓
   - `TEXT_CLIPPING` → BLOCK; hard ACTIVE-spec invariant (`logo_count>1`, `recompose`-over-`preserve`, `max_line_count` exceeded) → BLOCK

Wiring a real enforcing veto is a separate, explicitly-scoped phase.

## M. Local canary package

`scripts/_launch_readiness_visual_recap_canary.py` (new; ruff + ruff-format + mypy clean) →
`artifacts/visual_recap_canary/` (10 renders + `canary_records.json` + `CONTACT_SHEET.png`).
**No Telegram send. No DB writes.** ACTIVE specs read read-only.

| # | canary | logo | zone | scrim | src | lines | SPEC_MATCH | Art merged |
|---|---|---|---|---|---|---|---|---|
| 1 | news_01_dark_photo | 1 | lower_right | none | preserve | n/a | pass | **pass** |
| 2 | news_02_light_photo | 1 | lower_right | none | preserve | n/a | pass | **pass** |
| 3 | breaking_03_dark_dramatic | 1 | upper_right | none | preserve | n/a | rework (soft zone) | rework |
| 4 | breaking_04_light_photo | 1 | lower_right | none | preserve | n/a | pass_with_notes | pass_with_notes |
| 5 | data_05_existing_infographic (MINIMAL) | 1 | lower_right | none | preserve | **0** | pass_with_notes | pass_with_notes |
| 5b | data_05b_infographic_full_card **DESTROY TEST** | 1 | lower_right | none | preserve | 2 | **block** | **block — INFOGRAPHIC_DESTROYED** |
| 6 | data_06_generated_card (FULL) | 1 | lower_left | none | crop | 1 | rework (soft zone+fit) | rework |
| 7 | quote_07_light_portrait | 1 | lower_right | n/a | preserve | n/a | pass_with_notes | pass_with_notes |
| 8 | quote_08_dark_portrait | 1 | lower_right | n/a | preserve | n/a | pass_with_notes | pass_with_notes |
| 9 | recap_09_fallback_background | 0 (by contract) | — | — | — | — | — | — |

**Invariants held:** exactly one NNJ mark on every branded final image; BREAKING band retired
(`scrim=none` everywhere); number-preserve on the infographic (`lines=0` in MINIMAL); the
`INFOGRAPHIC_DESTROYED` guard fires; **no BLOCK on any accepted render**. The only non-PASS
results are soft REWORKs from the adaptive safe-corner scorer moving the (single) mark off
`lower_right` on busy/non-16:9 sources — behaviour, not a defect.

## N. Founder contact sheet path

`artifacts/visual_recap_canary/CONTACT_SHEET.png` — one compact sheet: NEWS ×2, BREAKING ×2,
DATA source-infographic, DATA infographic-destroy-test, DATA generated, QUOTE ×2, RECAP fallback,
each captioned with `logo / zone / scrim / art-decision`. Per-render PNGs + `canary_records.json`
alongside. (No CURRENT-vs-PROPOSED pairs — no renderer code was changed this phase.)

## O. Recap call path

```
ingestion
  → Story (services/triage_orchestrator.py writes NewsEventStoryLink for every considered event)
  → services/recap_event.py  [R1, FROZEN — reused, never reimplemented]
        load_story_events()                 confirmed members only: NEW_STORY + STORY_UPDATE
                                            + SUPPORTING_SOURCE + SEMANTIC_DUPLICATE
                                            (UNCERTAIN_MATCH / RELATED_STORY excluded)
        evaluate_recap_story_integrity()    Story Integrity Gate (temporal span bound
                                            recap_integrity_max_time_span_hours = 168.0)
        cluster_announcements()             threshold recap_announcement_cluster_threshold = 0.75
        count_unique_sources()              domain-based readiness signal
        evaluate_recap_readiness()          deterministic reasons, NO AI score
  → services/event_recap.py  [R2, shadow]
        build_event_recap_candidate()       → EventRecapCandidate (publishable = False, unconditional)
        _assert_no_publisher_contamination()  raises EventRecapEvidenceContaminationError
        synthesize_event_recap()            SHADOW-ONLY LLM synthesis (optional)
        _verify_synthesis_facts()           FactVerificationResult vs evidence
        _detect_internal_vocabulary_leak()
  → services/event_recap_scheduler.py  [R2.10-RUNTIME-2]  run_event_recap_scan()
        OFF  (default)  → EventRecapScanResult(mode="disabled"), no Story query, no side effect
        SHADOW          → build_event_recap_candidate(force_shadow=False), read-only, no task
        GENERATION      → generate_recap_for_story() once per candidate Story
  → services/event_recap_processor.py  generate_recap_for_story(story_id)
        Phase G.1 race-safe readiness gate BEFORE task creation (NOT_READY stays retry-able)
        exactly-once via create_task() one-task-per-(event_id, workflow_type), anchored to
            story.first_event_id
        discover_event_recap_media_if_needed() / render_branded_fallback_media() (Tier 1 / 2B / 3)
        _persist_selected_media() / _persist_source_snapshot()
  → CapabilityExecutor synthesis (precomputed_event_recap_candidate threaded through — no rebuild)
  → services/event_recap_review_service.py + event_recap_review_notifier.py  (internal editorial delivery)
  → publication gate: event_recap_pipeline (event_recap_pipeline_enabled=False) / final_post_publication
```

## P. Recap factual safety

**READY for R2 shadow.** Guarantees verified in code + tests:

- **No unrelated Story merge (bounded):** `load_story_events()` uses confirmed membership only;
  `evaluate_recap_story_integrity()` bounds the temporal span (168 h) and coherence;
  `cluster_announcements()` gates at 0.75. See §Q for the residual risk.
- **No invented chronology / numbers / quotes / causal claims:** timeline & verified facts are
  built deterministically from sanitized announcement signatures
  (`_sanitized_announcement_signature` / `_publisher_suffix_entities`, imported from FROZEN R1);
  the LLM synthesis pass is verified against that evidence (`_verify_synthesis_facts`,
  `_detect_internal_vocabulary_leak`) and **cannot change `publishable`**.
- **Publisher-suffix contamination:** `_assert_no_publisher_contamination()` runs on every build
  and raises loudly rather than tolerating a regression.
- **Sources preserved:** `readiness_source_count` (domain readiness) is kept separate from
  distinct evidence references (R2.2 fix).
- **Uncertainty preserved:** `evaluate_recap_readiness()` returns explicit deterministic reasons,
  never a synthetic score; `publishable = False` unconditionally in R2.

## Q. Recap Story pollution risk

**`RECAP_STORY_POLLUTION_RISK = true` (bounded; not currently reachable — generation OFF).**

`load_story_events()` correctly excludes weak links (UNCERTAIN_MATCH / RELATED_STORY). But if
triage **wrongly confirms** an unrelated event as `STORY_UPDATE` / `SEMANTIC_DUPLICATE` — exactly
the arXiv-abstract / polluted-multi-document-cluster false-duplicate class the parallel
`STORY-CONTINUITY-P0.1` work is chasing — Recap would summarise it together with the real event,
because it trusts confirmed membership.

Existing mitigations: the 168 h integrity span bound; the 0.75 announcement-cluster threshold;
the integrity gate still returns `eligible=False` for the generic-opener / arXiv pollution
fixtures (see §T — 5 `test_recap_story_integrity.py` cases: the *reject* holds, only the
`pair_entity_exclusions` **diagnostic** dict is empty — an explainability regression, pre-existing
on the base, not a safety regression).

**Proposed narrow Recap-side guard (NOT implemented — Founder decision; global clustering
untouched per §18):** in `build_event_recap_candidate()` / the integrity gate, when a confirmed
member's sanitized signature shares below-threshold entity overlap with the anchor cluster **and**
the arXiv-abstract / polluted-cluster signal from `services/story_identity_guard.py` fires, demote
that member to *context-only* (excluded from timeline + verified facts) rather than silently
folding it into the recap.

## R. Recap visual state

**NEEDS_FOUNDER_DECISION.** Recap must live in the same PULSE Telegram system as NEWS/BREAKING/
DATA/QUOTE. Current state: Tiers 1/2B use real Story media + the same `apply_master_news_branding()`
single-mark signature (consistent); Tier 3 (`build_recap_fallback_background()`) is a plain
unbranded background — branding applied once, later, at Final Post Review + publish time (never
twice). The two historical portrait recap mockups remain `NEEDS_FOUNDER_REVIEW` and were **not**
approved/rejected/promoted here. No silent recap redesign was done. If the Founder wants a
CURRENT-vs-PROPOSED recap card, that is a follow-up.

## S. Recap local canary

**`RECAP_CANARY = PASS_WITH_NOTES`.**

- Eligibility / integrity / announcement-identity / fact-verification exercised via the offline
  recap test suites: `test_recap_event.py`, `test_recap_story_integrity.py`,
  `test_recap_announcement_identity.py`, `test_event_recap.py`, `test_event_recap_scheduler.py`,
  `test_event_recap_processor.py`, `test_event_recap_capability.py` — **242 passed, 5 pre-existing
  failures** (§T), 1 skipped.
- Media / renderer / one-NNJ / final payload: `recap_09_fallback_background` renders; Tier-3
  fallback is unbranded by contract; branded tiers reuse the single-mark MASTER NEWS signature.
- Publication remains blocked: `EventRecapCandidate.publishable = False` (unconditional, line 601 +
  every return path); `run_event_recap_scan()` returns `mode="disabled"` with no Story query when
  `event_recap_scheduler_enabled=False`.
- Notes: the 5 pre-existing integrity-diagnostic failures (§Q/§T); Recap visual = NEEDS_FOUNDER_DECISION (§R).

## T. Tests

Focused visual/spec/art-director suite (`-p no:randomly`):

```
tests/test_brand_renderer.py  test_render_evidence_parity.py  test_design_spec_enforcement.py
test_design_spec_registry.py  test_art_director_number_mismatch_blocks.py
test_v2_10h_master_news_production.py  test_visual_renderer_constraints.py
test_visual_brand_core.py  test_presentation_director.py  test_news_telegram_presentation.py
test_director_control_plane_1b_art_director_live.py  test_director_control_plane_1a_art_director.py
→ 251 passed, 1 skipped, 0 failed
```

Recap suite:

```
tests/test_recap_event.py  test_recap_story_integrity.py  test_recap_announcement_identity.py
test_event_recap.py  test_event_recap_scheduler.py  test_event_recap_processor.py
test_event_recap_capability.py
→ 242 passed, 5 failed, 1 skipped
```

- **PASSED:** 493 (251 visual + 242 recap)
- **FAILED:** 5
- **SKIPPED:** 2
- **KNOWN_FAILURES (pre-existing on base `c6694b9`, reproduced on a pristine checkout with zero
  tracked edits):** `test_recap_story_integrity.py` — `test_case_b_accurate_generic_opener_fails_integrity`,
  `test_case_d_arxiv_large_language_models_generic_opener_fails_integrity`,
  `test_large_language_models_nine_member_lucky_pair_stress_case_still_fails`,
  `test_recent_generic_opener_with_near_duplicate_fails_integrity`,
  `test_autonomous_generic_opener_fails_integrity`. Each still asserts `result.eligible is False`
  correctly — the integrity gate **still rejects** these polluted/generic-opener stories; only the
  `result.metrics["pair_entity_exclusions"]` diagnostic dict is empty where the test expects
  `{"recent"}` / `{"autonomous"}` / etc. Safety behaviour intact; explainability regressed.
  Relevant to §Q and worth a fix in the Story-Continuity lineage, **out of scope here** (no Story
  Continuity / clustering changes permitted).
- **NEW_FAILURES: 0** ✅ (acceptance met)

## U. Static checks

- No tracked source file changed → no static regression possible on the codebase.
- New file `scripts/_launch_readiness_visual_recap_canary.py`: `ruff check` **All checks passed**,
  `ruff format --check` **already formatted**, `mypy` **Success: no issues found**.
- Repo has no `[tool.ruff]` config; `scripts/` already carries 12 pre-existing ruff errors in
  other files (not touched).
- **NEW_STATIC_ERRORS: 0** ✅

## V. Files changed

Tracked source: **none.**

Added (untracked / new):
- `docs/launch_readiness_visual_recap_parallel_1_report.md` (this report)
- `scripts/_launch_readiness_visual_recap_canary.py` (local canary; no side effects)
- `artifacts/visual_recap_canary/` (10 PNG renders + `canary_records.json` + `CONTACT_SHEET.png`)

## W. Commits

- `2882b8b` — `docs(launch-readiness): LAUNCH-READINESS-VISUAL-RECAP-PARALLEL-1 audit +
  local visual/recap canary` on branch `feature/launch-readiness-visual-recap-parallel-1`
  (base `c6694b9`). This §C/§W SHA-fill-in was folded back in with `--amend`, so the branch
  HEAD SHA differs from `2882b8b` by exactly this doc edit; `git log` on the branch is
  authoritative.

## X. Launch blocker matrix

| Area | State | Launch blocker? | Next action |
|---|---|---|---|
| NEWS visual | READY | No | none |
| BREAKING visual | READY | No | Founder note: confirm "urgency in native text, image = NEWS family" is the intended board reading |
| DATA visual — existing infographic | READY | No | none (source-preserving + hard guards verified) |
| DATA visual — generated card | NEEDS_FOUNDER_DECISION | No (safe; visible drift) | Founder: compact corner stat vs board hero-metric → decide; follow-up spec + renderer phase if hero-metric |
| QUOTE visual | NEEDS_FOUNDER_DECISION | No | Founder: red quote-mark motif + role/title line + stop baking `NP`/label → decide; follow-up `telegram_quote` v2 + `QuoteCandidate.role` + renderer |
| VisualSpec | NEEDS_FOUNDER_DECISION | No (dev only) | prod control-plane DB still on v1 (split-brain) → authorize `scripts/activate_visual_spec_v2.py` replay in a later deploy phase; confirm `logo_zone`/`source_image_treatment` stay **soft** |
| Art Director | READY (shadow) | No | shadow only, no veto wired; merge/hard-failure logic correct; wiring an enforcing veto = separate phase |
| single NNJ | READY | No | invariant held in all 10 canaries + structural + Art Director `DUPLICATE_NNJ_BRAND_MARK` hard-BLOCK |
| Recap factual safety | READY (R2 shadow) | No | R1 gate FROZEN; contamination assert; synthesis verification; `publishable=False` unconditional |
| Recap Story pollution risk | RECAP_STORY_POLLUTION_RISK = true (bounded) | No (generation OFF) | Founder: adopt the narrow Recap-side context-only guard (§Q); do NOT touch global clustering |
| Recap visual | NEEDS_FOUNDER_DECISION | No | 2 unresolved recap mockups remain NEEDS_FOUNDER_REVIEW; no silent redesign |
| Recap final payload | READY | No | 2-message structure (media + full factual text); publication blocked |
| public publication gate | READY | No | `pulse_recap_enabled` / `event_recap_scheduler_enabled` / `event_recap_generation_enabled` / `event_recap_pipeline_enabled` all False; `run_event_recap_scan()` → `mode="disabled"` |

Classification: READY = NEWS, BREAKING, DATA-infographic, Art Director, single-NNJ, Recap fact
safety, Recap final payload, publication gate. NEEDS_FOUNDER_DECISION = DATA-generated, QUOTE,
VisualSpec (prod replay + soft/hard), Recap Story-pollution guard, Recap visual, **and the board
proxy confirmation (§D)**. NEEDS_FIX = none. BLOCKED = none.

## Y. Recommended next production phase

1. **Founder visual review** against the *actual* board: confirm the `master_prototype.png`
   proxy; rule on DATA generated hero-metric vs compact corner; rule on the QUOTE composition
   (red quote-mark motif, author role line, baked `NP`/label). Produce CURRENT-vs-PROPOSED sheets
   only for whatever the Founder wants changed.
2. **`VISUAL-SPEC-V2-PROD-REPLAY`** (deploy-gated, explicitly authorized): replay the idempotent
   `scripts/activate_visual_spec_v2.py` against the **production** control-plane DB to end the v1/v2
   split-brain; no renderer change.
3. **`RECAP-STORY-POLLUTION-GUARD-1`**: implement the narrow Recap-side context-only demotion
   (§Q) + restore the `pair_entity_exclusions` diagnostic; still shadow, generation OFF.
4. Only after 1–3: a scoped **Art Director enforcing-veto** phase, then a **Recap generation
   shadow** phase.

---

## Final verdict

Technical visual + recap work is safe: no production mutation; single-NNJ, BREAKING-band-retired,
number-preserve, and INFOGRAPHIC_DESTROYED invariants all verified in local canaries; NEW_FAILURES
= 0; NEW_STATIC_ERRORS = 0. But a Founder visual decision remains open on DATA-generated and QUOTE
(genuine board-vs-renderer drift), the ACTIVE-spec production replay, the Recap Story-pollution
guard, and Recap visual direction — **and the authority-#1 board image never arrived, so the
proxy must be Founder-confirmed.**

**LAUNCH_READINESS_VISUAL_RECAP_PARTIAL**

Do not deploy. Wait for Founder review.
