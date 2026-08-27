# Phase V2.2B — Complete Live Three-Model Recomposition Bake-Off — Report

Canonical HEAD unchanged: `f8a604b5d4e113e53b96a2655ec38644eeafbef0`. Nothing committed.

## 1. Preflight

- `git rev-parse HEAD`: `f8a604b5d4e113e53b96a2655ec38644eeafbef0`.
- `git status --short` / `git diff --stat`: unchanged from V2.2A's own end-state (see §24/§25
  below) plus this phase's own new, untracked files.
- Alembic: `b0e95ddf7b05 (head)`.
- `automation_worker`: `running`, `StartedAt=2026-08-25T20:14:29Z`, `RestartCount=0`. Three clean
  `automation_cycle_finished` log lines across the session (10:55, 11:34, 12:13), zero
  `automation_cycle_failed`/`TelegramAuthenticationError` in the last 6h.
- `presentation_director_mode`: `off`. No production renderer/recomposition path active.

## 2. Immutability proof

Checked before any paid call:
- `gemini_image_adapter.py` / `openai_image_adapter.py` / `nnj_visual_recomposition_bakeoff.py`:
  file mtimes all predate the V2.2A smoke manifest's own `generated_at_utc` timestamp — no edit
  since the smoke run.
- `build_recomposition_prompt()`'s live output byte-for-byte matches the `canonical_prompt` string
  recorded in the V2.2A smoke manifest: **MATCH: True**.
- All 3 source images' SHA-256 re-verified against `v2_1_bakeoff_sources/provenance.json`: **all 3
  MATCH: True**.
- `git status --short` identical to the V2.2A end-state (no new modification to any tracked file).

Immutability held on every axis — proceeded.

## 3. Preserved Case-1 results (copied, not regenerated)

| Model | Source SHA-256 | Output SHA-256 | Request ID | Dimensions | Latency | Usage (in/out) | Est. cost |
|---|---|---|---|---|---|---|---|
| gemini-3.1-flash-image | `c3126a01…` | `65597fb1…` | `v1_Chd1eW1RYXVfbEVhcWx2ZElQaU1UdjhBTRIXdXltUWF1X2xFYXFsdmRJUGlNVHY4QU0` | 1376×768 | 16.78s | 552 / 1431 | $0.067 |
| gemini-3-pro-image | `c3126a01…` | `3a9905b9…` | `v1_ChYwU21RYXFHRExhSFBzZ0x6amFycERnEhYwU21RYXFHRExhSFBzZ0x6amFycERn` | 1376×768 | 22.38s | 552 / 1241 | $0.134 |
| gpt-image-2 | `c3126a01…` | `9b7de3c6…` | `req_3f551239906d44749a8138d1d45eb1ed` | 1536×1024 | 24.12s | 1798 / 158 | $0.05 |

Copied byte-for-byte into `originals/case1_hero_product_iphone/` — post-copy SHA-256 verified
identical to the smoke manifest's own recorded hash for all 3 (the script raises on any mismatch;
none occurred). **Not regenerated.**

## 4. Exact six new matrix cells executed

Case 2 (`case2_gadget_geometry_detail`, source SHA-256 `83761c78…`) × 3 models; Case 3
(`case3_bright_promotional_scene`, source SHA-256 `36ccc2bb…`) × 3 models — all using the
identical canonical prompt (byte-verified equal to Case 1's and the V2.2A smoke's own).

## 5. Attempts / retries

**All 6 succeeded on the first attempt. Zero retries.** (`retries: []` in the manifest.)

## 6. Six new output paths

- `assets/brand/newsroom_visuals/v2_2_bakeoff_complete/originals/case2_gadget_geometry_detail/gemini__gemini-3.1-flash-image.jpg`
- `assets/brand/newsroom_visuals/v2_2_bakeoff_complete/originals/case2_gadget_geometry_detail/gemini__gemini-3-pro-image.jpg`
- `assets/brand/newsroom_visuals/v2_2_bakeoff_complete/originals/case2_gadget_geometry_detail/openai__gpt-image-2.png`
- `assets/brand/newsroom_visuals/v2_2_bakeoff_complete/originals/case3_bright_promotional_scene/gemini__gemini-3.1-flash-image.jpg`
- `assets/brand/newsroom_visuals/v2_2_bakeoff_complete/originals/case3_bright_promotional_scene/gemini__gemini-3-pro-image.jpg`
- `assets/brand/newsroom_visuals/v2_2_bakeoff_complete/originals/case3_bright_promotional_scene/openai__gpt-image-2.png`

## 7. Final nine-result package

`assets/brand/newsroom_visuals/v2_2_bakeoff_complete/` — `originals/<case_id>/<provider>__<model_id>.<ext>`
for all 9 cells (3 copied + 6 new), `manifest.json`, `evaluation.json`, `evaluation.csv`,
`CONTACT_SHEET_V2_2_FINAL.jpg`, `CASE_1_DETAIL.jpg`, `CASE_2_DETAIL.jpg`, `CASE_3_DETAIL.jpg`. No
NNJ overlay, color-grading, sharpening, cropping, retouching, or re-compression applied to any
provider original — only the contact-sheet/detail-sheet copies are thumbnail-normalized for
display, per Stage 8's own "display normalization allowed for contact sheets only" rule.

## 8. Final contact-sheet path

`assets/brand/newsroom_visuals/v2_2_bakeoff_complete/CONTACT_SHEET_V2_2_FINAL.jpg` — 3 rows (one
per case) × 4 columns (source, Gemini Flash, Gemini Pro, GPT-Image-2), same order for all 3 cases.

## 9-11. Source-by-source analysis

### Case 1 — iPhone (hero product)
All 3 models preserved the triple-lens camera module, Apple logo, and orange colorway with equal
fidelity (5/5 each). Differentiation is in composition only: **Gemini 3 Pro** made the most
deliberate editorial change (isolated hero-shot, gold-gradient background swap); **GPT-Image-2**
was the most conservative (closest to source framing/background); **Gemini Flash** sat in between.
No hardware/logo alteration in any of the 3. Best branding safe-zone: Gemini Flash/GPT-Image-2 tied
(clean orange lower area); Gemini Pro close behind.

### Case 2 — second gadget (keyboard + Duolingo phone)
The clearest differentiator in the whole bake-off. **Gemini 3.1 Flash preserved the keyboard's
individual keys and the Duolingo logo/wordmark/tagline with the highest precision of any result in
the bake-off** (factual fidelity 5/5, zero flags). **Gemini 3 Pro** kept the keyboard but re-lit it
enough to shift its material appearance (flagged `MINOR_VISUAL_MUTATION`). **GPT-Image-2 removed
the keyboard entirely**, replacing it with a flat solid-blue background — the one
`MAJOR_VISUAL_MUTATION` in the whole bake-off, directly contradicting this case's purpose
(geometry/detail preservation of a second physical device). Precision-handling ranking: **Gemini
Flash > Gemini Pro > GPT-Image-2**, not close.

### Case 3 — bright/saturated promotional scene (Snapchat kiosk)
All 3 preserved the kiosk's shape, yellow color, and Snapchat ghost logo (no hardware-identity
issue for any). Differences: **Gemini Flash** kept the real environment and the incidental
bystander (most source-faithful, but weakest safe-zone — the kiosk fills nearly the whole frame).
**Gemini Pro** removed the bystander and isolated the kiosk on a clean gradient (best safe-zone of
the three for this case; screen's own photo-content simplified from source, a minor non-hardware
drift). **GPT-Image-2** also removed the bystander, flattened the background to solid yellow (most
graphic/least photorealistic), but produced the **most legible on-screen UI text** ("LOOK HERE",
"Capture whole body" both readable) — no hardware loss here, unlike its Case 2 result. No model
hallucinated new promotional content beyond what the source already showed.

## 12. Complete nine-output evaluation table

See `assets/brand/newsroom_visuals/v2_2_bakeoff_complete/evaluation.json` /`.csv` for the full
machine-readable table (all 9 rows, all rubric fields, free-text notes). Summary:

| Case | Model | Fidelity | Composition | Safe-Zone | Photorealism | Prompt Adh. | Edit Strength | Flag |
|---|---|---|---|---|---|---|---|---|
| 1 | Gemini Flash | 5 | 3 | 4 | 5 | 5 | APPROPRIATE | NONE |
| 1 | Gemini Pro | 5 | 4 | 4 | 5 | 4 | APPROPRIATE | NONE |
| 1 | GPT-Image-2 | 5 | 3 | 4 | 5 | 5 | TOO_CONSERVATIVE | NONE |
| 2 | Gemini Flash | 5 | 3 | 3 | 5 | 5 | TOO_CONSERVATIVE | NONE |
| 2 | Gemini Pro | 4 | 4 | 4 | 4 | 4 | APPROPRIATE | MINOR |
| 2 | GPT-Image-2 | 3 | 3 | 5 | 3 | 3 | TOO_AGGRESSIVE | **MAJOR** |
| 3 | Gemini Flash | 5 | 3 | 2 | 5 | 4 | TOO_CONSERVATIVE | NONE |
| 3 | Gemini Pro | 4 | 4 | 4 | 4 | 4 | APPROPRIATE | MINOR |
| 3 | GPT-Image-2 | 4 | 3 | 4 | 3 | 5 | TOO_AGGRESSIVE | NONE |

## 13. Critical fidelity flags

**Zero `CRITICAL_PRODUCT_MUTATION` across all 9 results.** One `MAJOR_VISUAL_MUTATION`
(GPT-Image-2, Case 2 — real keyboard removed). Two `MINOR_VISUAL_MUTATION` (Gemini Pro, Case 2 and
Case 3 — lighting/material drift and simplified screen content, respectively). Per the rubric's
own rule, GPT-Image-2's Case 2 result is NOT rescued by its otherwise-fine aesthetic scores.

## 14. Model-level aggregate metrics

| Metric | Gemini 3.1 Flash | Gemini 3 Pro | GPT-Image-2 |
|---|---|---|---|
| Mean factual fidelity | **5.0** | 4.33 | 4.0 |
| Worst factual fidelity | **5** | 4 | 3 |
| CRITICAL flags | 0 | 0 | 0 |
| MAJOR flags | 0 | 0 | **1** |
| MINOR flags | 0 | 2 | 0 |
| Mean composition | 3.0 | **4.0** | 3.0 |
| Mean safe-zone | 3.0 | 4.0 | **4.33** |
| Mean photorealism | **5.0** | 4.33 | 3.67 |
| Mean prompt adherence | **4.67** | 4.0 | 4.33 |
| Edit strength (Cons./Appr./Aggr.) | 2 / 1 / 0 | 0 / 3 / 0 | 1 / 0 / 2 |

## 15. Per-model cost

| Model | Successful outputs | Estimated total | Actual (provider-reported) |
|---|---|---|---|
| Gemini 3.1 Flash Image | 3 | $0.201 | not reported by API — ESTIMATE only |
| Gemini 3 Pro Image | 3 | $0.402 | not reported by API — ESTIMATE only |
| GPT-Image-2 | 3 | $0.15 | not reported by API — ESTIMATE only |
| **Final 9-generation bake-off total** | **9** | **$0.753** | — |

**PRIOR FAILED GEMINI ATTEMPT BILLING (V2.2 attempt #1, 12 attempts): UNKNOWN — not independently
proven, not blended into the figures above.** Check Google AI Studio / Cloud Billing directly.

## 16. Per-model latency

| Model | Total (3 calls) | Average |
|---|---|---|
| Gemini 3.1 Flash Image | 42.49s | **14.16s (fastest)** |
| Gemini 3 Pro Image | 73.70s | 24.57s (slowest) |
| GPT-Image-2 | 69.87s | 23.29s |

## 17. Quality/cost comparison

Priority order applied (critical failures → factual fidelity → composition → safe-zone →
reliability → cost → latency): **Gemini 3.1 Flash Image wins on the top-priority criteria**
(zero flags, highest and most consistent factual fidelity) while also being the cheapest of the
two Gemini models and the fastest of all three. Gemini 3 Pro's real strength (composition) comes
at ~2× Flash's cost and with 2 minor fidelity flags. GPT-Image-2 is cheapest overall but carries
the bake-off's only MAJOR mutation and the lowest/most volatile fidelity — its safe-zone/cost
advantages don't outweigh that under this priority order.

## 18-20. Recommendations (not wired, not automatic)

- **18. DEFAULT RECOMPOSITION MODEL: Gemini 3.1 Flash Image.** Highest and most consistent factual
  fidelity (mean 5.0, zero mutation flags across all 3 cases), fastest, and cheaper than Gemini
  Pro. Edit strength trends conservative-to-appropriate — a safe default for factual-news use.
- **19. QUALITY ESCALATION MODEL: Gemini 3 Pro Image.** Meaningfully better composition (mean 4.0
  vs 3.0) when that matters more than raw speed/cost, at ~2× Flash's per-image cost — but its 2
  MINOR_VISUAL_MUTATION flags mean an editor should still spot-check outputs before using it
  unsupervised. Gemini Pro does **not** materially outperform Flash overall (fidelity is actually
  slightly lower); this is a composition-for-fidelity tradeoff, not a strict upgrade.
- **20. FALLBACK: not separately needed** — Flash and Pro can serve as each other's fallback.
  **REJECT / DO NOT USE AS DEFAULT (pending more evidence): GPT-Image-2.** Its one
  MAJOR_VISUAL_MUTATION (Case 2's real keyboard deleted) and lowest/most volatile factual fidelity
  (mean 4.0, worst 3) are disqualifying for a factual-news default under this priority order,
  despite it being cheapest and having the best safe-zone score. This is based on 3 samples per
  model only — not a definitive statistical verdict, and GPT-Image-2's Case 1 and Case 3 results
  were both clean (no flags) — but the one major failure observed is exactly the kind of risk this
  bake-off exists to catch.

GPT-Image-2 also does **not** materially outperform either Gemini model on factual fidelity (§7 of
the questions above) — it underperforms both.

## 21. Exact review artifact paths

- Final contact sheet: `assets/brand/newsroom_visuals/v2_2_bakeoff_complete/CONTACT_SHEET_V2_2_FINAL.jpg`
- Per-case detail sheets: `assets/brand/newsroom_visuals/v2_2_bakeoff_complete/CASE_1_DETAIL.jpg`,
  `CASE_2_DETAIL.jpg`, `CASE_3_DETAIL.jpg`
- All 9 provider originals: `assets/brand/newsroom_visuals/v2_2_bakeoff_complete/originals/<case_id>/<provider>__<model_id>.<ext>`
- Evaluation table: `assets/brand/newsroom_visuals/v2_2_bakeoff_complete/evaluation.json` and
  `evaluation.csv`
- Full metadata manifest: `assets/brand/newsroom_visuals/v2_2_bakeoff_complete/manifest.json`

## 22. Side-effect audit

| Check | Result |
|---|---|
| New paid successful generations | 6 (≤ 6 cap, exact) |
| Total valid bake-off cells | 9 |
| Telegram sends | 0 |
| Publications | 0 |
| Production recomposition calls | 0 |
| EVENT_RECAP executions caused by this phase | 0 |
| `presentation_director_mode` | `off`, unchanged |
| `automation_worker` restarts | 0 |
| Commit made | No |

## 23. `automation_worker` final state

`Status=running`, `StartedAt=2026-08-25T20:14:29.785185817Z` (unchanged), `RestartCount=0`.

## 24. `git diff --stat`

```
core/config.py                                     |   5 +
integrations/llm_gateway/image_protocol.py         | 150 ++++++++++++++++++++-
.../llm_gateway/providers/mock_image_adapter.py    |  29 +++-
3 files changed, 175 insertions(+), 9 deletions(-)
```

## 25. `git status --short`

```
 M core/config.py
 M integrations/llm_gateway/image_protocol.py
 M integrations/llm_gateway/providers/mock_image_adapter.py
?? assets/brand/newsroom_visuals/
?? docs/nnj_editorial_visual_system_v1.md
?? docs/nnj_source_faithful_editorial_visual_recomposition_v1.md
?? docs/phase_v2_1_provider_bakeoff_preparation_report.md
?? docs/phase_v2_2_live_bakeoff_report.md
?? docs/phase_v2_2a_protocol_repair_and_smoke_report.md
?? docs/phase_v2_2b_complete_bakeoff_report.md
?? integrations/llm_gateway/providers/gemini_image_adapter.py
?? integrations/llm_gateway/providers/openai_image_adapter.py
?? scripts/nnj_v2_2_live_bakeoff_run.py
?? scripts/nnj_v2_2a_protocol_smoke_run.py
?? scripts/nnj_v2_2b_complete_bakeoff_run.py
?? scripts/nnj_visual_recomposition_bakeoff.py
?? tests/test_v2_1_bakeoff_harness.py
?? tests/test_v2_1_gemini_image_adapter.py
?? tests/test_v2_1_image_generation_protocol.py
?? tests/test_v2_1_openai_image_adapter.py
?? tests/test_v2_2a_gemini_response_parsing.py
```

No commit made.

## 26. Remaining open questions before production integration

1. **Sample size**: 3 images per model is enough to catch a clear failure pattern (GPT-Image-2's
   keyboard deletion) but not enough for a statistically confident ranking — a larger sample
   before final production commitment would sharpen confidence, especially for Gemini Pro's
   fidelity-vs-composition tradeoff.
2. **Billing verification**: both the 12 prior failed Gemini attempts (V2.2 attempt #1) and these
   9 successful generations' real dollar cost should be confirmed against each provider's own
   billing console — no provider response in this bake-off reported an actual dollar figure.
3. **NNJ safe-zone with real branding**: safe-zone scores here are a human visual estimate; once a
   model is chosen, the actual deterministic NNJ line/pulse/mark should be composited onto a few
   real outputs to confirm the zone truly doesn't collide with product/logo/text.
4. **GPT-Image-2's aggressiveness**: worth testing whether a stronger "preserve all real physical
   objects in frame" instruction changes its behavior, or whether this is a systematic model
   tendency — not yet known from 3 samples.
5. **No production wiring exists yet** for whichever model is chosen — `ImageGenerationGateway`
   consumer wiring, a real "live" mode value (today only `off`/`dry_run` exist in
   `meme_image_generation_mode`'s type system), retry/cost-ceiling policy, and Telegram/
   EVENT_RECAP integration are all still to be designed and separately authorized.

## Verdict

**A) NINE-CELL LIVE BAKE-OFF COMPLETE — READY FOR USER MODEL SELECTION**

All 9 cells succeeded (3 preserved from V2.2A + 6 new), zero retries needed, zero critical
mutations, one major mutation isolated to GPT-Image-2/Case 2. Full visual review package is ready
at `assets/brand/newsroom_visuals/v2_2_bakeoff_complete/`. No production integration performed.
