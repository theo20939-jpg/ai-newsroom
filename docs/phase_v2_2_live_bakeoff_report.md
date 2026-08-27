# Phase V2.2 — Live Three-Model Recomposition Bake-Off — Report

Canonical HEAD unchanged. Nothing in this phase has been committed.

## Step 1 — Credential recheck

| | Status | Variable | Model access |
|---|---|---|---|
| Google/Gemini | PRESENT | `GEMINI_API_KEY` | `gemini-3.1-flash-image` / `gemini-3-pro-image` both returned HTTP 200 on a metadata GET |
| OpenAI | PRESENT | `OPENAI_API_KEY` | `gpt-image-2` resolved via free `models.retrieve` |

Both PRESENT as expected — proceeded to Step 2.

## Step 2 — Live harness preflight

- Harness path: `scripts/nnj_visual_recomposition_bakeoff.py` (V2.1, reused unchanged) +
  `scripts/nnj_v2_2_live_bakeoff_run.py` (new, V2.2-specific orchestration — output
  organization/retry bookkeeping/contact sheet only; imports the V2.1 harness's own case loader,
  canonical prompt, and model matrix rather than redefining them).
- dry-run/live separation: confirmed (`--live` gate, defaults to dry run).
- 3 canonical source images + SHA-256 verified against `provenance.json` (all matched).
- Model matrix confirmed: `gemini-3.1-flash-image`, `gemini-3-pro-image`, `gpt-image-2` — no
  substitutions.
- `--max-successful-generations` = 9 confirmed as the hard cap in code.
- No Telegram/production-path import found in either script (grep-verified).
- `presentation_director_mode` = `off` (confirmed).
- `automation_worker`: RestartCount 0, `StartedAt` unchanged from session baseline.
- Final dry run immediately before live execution: `planned_runs=9`,
  `network_image_generation_calls=0`, `successful_paid_generations=0` — matched requirement exactly.

## Step 3 — Live execution (AUTHORIZED)

Ran exactly one generation attempt per source/model pair (9 pairs), with exactly one retry
permitted per pair on a provider-typed error, using the identical source/model/prompt/operation.

**Result: 0/9 successful. All 9 pairs failed on both the initial attempt and the retry — 18 total
attempts, 9 retries (all disclosed below).**

Root causes (two distinct, genuine provider/adapter contract failures — not transient, so the
retry correctly reproduced the identical error both times):

1. **Gemini (`gemini-3.1-flash-image`, `gemini-3-pro-image`)** — the real Interactions API
   response is **not** the `output_image`/`outputImage` shape the V2.1 adapter's docstring
   (dated 2026-08-27) inferred from incomplete documentation. The actual top-level response keys
   were: `created, id, model, object, service_tier, status, steps, usage, updated` — this looks
   like an **asynchronous job/interaction resource** (a `status` + `steps` shape), not a
   synchronous image payload. Real latency was 11.6s–34.0s per call, consistent with the API
   genuinely doing work — this was a live, working call that our adapter simply could not parse,
   not a rejected/unavailable model.
   - **Cost risk disclosure**: the response included a `usage` field. We cannot rule out that
     Google metered/billed these 6 calls (3.1 Flash × 3 cases + 3 Pro × 3 cases) even though we
     never received a parseable image or a dollar figure — `actual_cost_usd` in the manifest is
     `0` only because no adapter response was ever successfully constructed, not because we have
     confirmation of zero billing. This should be checked against the Google Cloud/AI Studio
     billing console directly, outside this harness.
2. **OpenAI (`gpt-image-2`)** — every call failed fast (150ms–1.2s, consistent with a
   request-validation-time rejection before any generation work started) with
   `400 Bad Request: Unknown parameter: 'response_format'`. The live `images.edit` endpoint no
   longer accepts `response_format` for this model, contradicting the V2.1 adapter's own
   introspection-based verification. Because this fails at request validation, essentially no
   generation cost should have been incurred (OpenAI does not bill rejected requests).

Both are **adapter-side contract bugs surfaced for the first time by this live run** — exactly
what this bake-off was for. No image-generation capacity issue, no account restriction, no
model-unavailability; the models themselves are reachable, but our unverified assumptions about
their exact response schema were wrong in two different ways.

## Step 4 — Saved outputs

No provider ever returned a usable image, so there are no generated images to preserve.
Directory created: `assets/brand/newsroom_visuals/v2_2_bakeoff_live/` containing:
- `manifest.json` — full machine-readable record of all 9 pairs, both attempts each, latencies,
  error messages, retry disclosure.
- `CONTACT_SHEET_V2_2.jpg` — 3 rows (one per source) × 4 columns (source, then the 3 models in
  the required order); every model cell shows a red "FAILED" placeholder since no output existed
  to place there.

## Step 5 — Factual fidelity review

**Not applicable — zero successful outputs exist to review.** No hardware/silhouette/logo/UI
scoring was possible.

## Step 6 — Cost / latency

| Provider | Model | Case | Attempts | Retried | Latency (final attempt) | Request ID |
|---|---|---|---|---|---|---|
| gemini | gemini-3.1-flash-image | case1 | 2 | yes | 11.6s | none returned |
| gemini | gemini-3-pro-image | case1 | 2 | yes | 20.4s | none returned |
| openai | gpt-image-2 | case1 | 2 | yes | 1.16s | none returned |
| gemini | gemini-3.1-flash-image | case2 | 2 | yes | 12.3s | none returned |
| gemini | gemini-3-pro-image | case2 | 2 | yes | 20.3s | none returned |
| openai | gpt-image-2 | case2 | 2 | yes | 0.42s | none returned |
| gemini | gemini-3.1-flash-image | case3 | 2 | yes | 15.0s | none returned |
| gemini | gemini-3-pro-image | case3 | 2 | yes | 34.0s | none returned |
| openai | gpt-image-2 | case3 | 2 | yes | 0.29s | none returned |

- Total successful generations: **0**
- Total attempts: **18**
- Retries: **9** (one per pair, all disclosed above, all reproduced the identical error)
- Gemini Flash cost: **$0 confirmed by our harness; NOT independently confirmed as $0 by Google's
  billing system — see Step 3 disclosure**
- Gemini Pro cost: **same disclosure**
- GPT-Image-2 cost: **$0 (high-confidence — fast 400 rejections, no generation work started)**
- Total actual/estimated bake-off cost: **$0 confirmed; Gemini legs carry an unresolved billing
  disclosure above**

## Step 7 — Model comparison

**Not answerable — no successful outputs from any model.** No factual-fidelity, composition,
safe-zone, conservatism/aggressiveness, or quality/cost-ratio comparison can be made. No
`DEFAULT`/`QUALITY ESCALATION` candidate can be recommended. Every model is currently a de facto
**REJECT** state, but only because of adapter-side response-parsing bugs, not demonstrated model
quality — this distinction matters for what happens next.

## Step 8 — Strict side-effect boundary

| Check | Result |
|---|---|
| Telegram sends | 0 |
| Publications | 0 |
| Production recomposition calls | 0 |
| EVENT_RECAP executions caused by this phase | 0 |
| `presentation_director_mode` | `off`, unchanged |
| `automation_worker` restarts | 0, unchanged (`StartedAt` identical to session baseline) |
| `content_cycle.py` / `brand_renderer.py` modified | No |
| Commit made | No |

All boundaries held.

## Paths

- Contact sheet: `assets/brand/newsroom_visuals/v2_2_bakeoff_live/CONTACT_SHEET_V2_2.jpg`
  (all 9 model cells show FAILED placeholders — no successful generations exist)
- Generated images: **none exist** (0/9 succeeded)
- Manifest: `assets/brand/newsroom_visuals/v2_2_bakeoff_live/manifest.json`

## Verdict

**B) ONE OR MORE MODELS FAILED OR WERE UNAVAILABLE — REVIEW REQUIRED**

Both adapters have real, root-caused, fixable contract bugs (Gemini: response shape is an
async-job/`steps` object, not the assumed `output_image` field; OpenAI: `response_format` is now
an unrecognized parameter for `images.edit`). No model was unreachable or access-denied. Zero
paid generations succeeded; the Gemini cost/billing disclosure above should be checked before any
further live attempts. Not proceeding further without new explicit authorization for a corrected
adapter + re-run.
