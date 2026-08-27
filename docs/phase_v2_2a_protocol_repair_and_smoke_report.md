# Phase V2.2A — Live Contract Repair + Three-Model Protocol Smoke — Report

Canonical HEAD unchanged throughout: `f8a604b5d4e113e53b96a2655ec38644eeafbef0`. Nothing committed.

## 1. Preflight

- `git rev-parse HEAD`: `f8a604b5d4e113e53b96a2655ec38644eeafbef0` — matched expectation.
- `git status --short`: only V1/V2/V2.1/V2.2 visual-track files (modified/untracked); no
  production file touched.
- `git diff --stat`: `core/config.py` (+5), `integrations/llm_gateway/image_protocol.py` (+150/-9
  net), `integrations/llm_gateway/providers/mock_image_adapter.py` (+29) — all pre-existing V2.1
  work, unchanged by this phase (the two adapter files are untracked, not modified, so they don't
  appear in `--stat`).
- Alembic: `b0e95ddf7b05 (head)`.
- `automation_worker`: `Status=running`, `StartedAt=2026-08-25T20:14:29Z`, `RestartCount=0`.
  Latest cycle in the last log tail finished cleanly (`automation_cycle_finished`, 2026-08-27
  11:34:23). `grep -i "automation_cycle_failed\|TelegramAuthenticationError"` over the last 6h of
  logs: **zero matches**.

## 2. Preserved first-failure evidence

`assets/brand/newsroom_visuals/v2_2_bakeoff_live/manifest.json` and `CONTACT_SHEET_V2_2.jpg`
(attempt #1) were not modified, deleted, or overwritten. Added
`ANNOTATION_ATTEMPT_1_CONTRACT_FAILURE.md` alongside them, stating plainly that attempt #1 was an
adapter contract failure, not a completed bake-off, and preserving the exact attempt/retry counts
(12 Gemini attempts = 6 original + 6 retries; 6 OpenAI attempts = 3 original + 3 retries — read
directly from the preserved manifest's own `attempts`/`retried` fields, not asserted independently).

## 3. Gemini contract repair — Interactions API

`google-genai` SDK: **NOT INSTALLED** in this environment (confirmed again — `pip show
google-genai` → not found). The adapter remains raw-`httpx`-based, unchanged in that respect.

**Root cause** (confirmed via WebFetch of `ai.google.dev/api/interactions-api`, 2026-08-27):
`interaction.output_image` is a **Python SDK-only computed property**, not a raw JSON response
field. A raw-HTTP adapter must read the image out of `steps` itself. The real response shape:
`status` ∈ `{in_progress, requires_action, completed, failed, cancelled, incomplete,
budget_exceeded, queued}`; `steps` is an array of step objects; a `model_output` step's `content`
array carries typed blocks, an image block being exactly `{"type": "image", "data": "<base64>",
"mime_type": "...", "resolution": "...", "uri": <optional>}`.

Also confirmed (WebFetch of `ai.google.dev/gemini-api/docs/image-generation`, 2026-08-27): the API
is **synchronous by default** — matches the 11.6s–34.0s single-POST latencies observed in the
first failed live run (the call had already fully completed; the adapter just looked in the wrong
place).

## 4. Gemini extraction/polling fix

`integrations/llm_gateway/providers/gemini_image_adapter.py`, fully rewritten:
- `_extract_image_from_payload()`: (A) tries `output_image`/`outputImage` convenience field first
  (defensive, in case a future revision adds one), (B) otherwise scans `steps` for a
  `model_output` step's `content` for a `type == "image"` block.
- `_await_terminal()`: only enters polling when a response's own `status` is `in_progress`/
  `queued`; polls `GET /interactions/{id}` every `_POLL_INTERVAL_SECONDS = 2.0`, hard-stops at
  `_MAX_POLL_WAIT_SECONDS = 90.0` (naming mirrors `core/config.py`'s own `*_poll_interval_seconds`
  / `*_timeout_seconds` convention) — never polls forever.
- `background=True` is never set; the normal path is trusted to complete synchronously, per §3.
- `response_format` is now **always** sent (`{"type": "image", "mime_type": "image/jpeg"[,
  "aspect_ratio": ...]}`), not only when `target_aspect_ratio` is set — omitting it risked a
  text-only completion.
- `Api-Revision: 2026-05-20` header added to every request (POST and polling GET), pinning the
  confirmed `steps`-based schema explicitly.
- `_map_usage()`: reads `total_input_tokens`/`total_output_tokens` from the real `Usage` object
  shape (not `input_tokens`/`output_tokens` — a different shape than OpenAI's).

## 5. Gemini tests

New `tests/test_v2_2a_gemini_response_parsing.py` — all 9 requested scenarios, plus 2 request-shape
regressions, all using `httpx.MockTransport` (Barrier-3 convention): completed+`output_image`;
completed+image-in-steps; in_progress→poll→completed+image; in_progress→poll→failed; completed
text-only (no image); malformed base64 in a steps image block; polling timeout (bounded, never
unbounded); usage metadata mapped; request/model ID preserved; `response_format` always sent;
`Api-Revision` header on every request (including polling GETs). **13/13 passing.**

## 6. Installed OpenAI SDK version

`openai==2.45.0` (unchanged from V2.1).

## 7. `gpt-image-2` request-signature root cause

`inspect.signature(AsyncImages.edit)` still lists `response_format` as an accepted keyword — the
SDK's type stub is generic across all image models. WebSearch (2026-08-27, OpenAI community/docs
corroboration) confirmed: **`response_format` is not supported for any GPT image model**
(gpt-image-1/1.5/2, chatgpt-image-latest) — they always return base64-encoded JSON unconditionally;
the parameter only ever applied to the older `dall-e-2`/`dall-e-3` models. A parameter can be
SDK-valid but still server-rejected for a specific model — exactly what happened.

## 8. OpenAI request fix

`response_format` removed from the `images.edit` call entirely — not substituted with another
field. `model`, `image`, `prompt`, `size` unchanged; MIME/filename tuple construction unchanged;
canonical prompt unchanged.

## 9. OpenAI tests

`tests/test_v2_1_openai_image_adapter.py` re-run unmodified (all still valid) plus one new
regression test: `test_response_format_is_never_sent` — asserts `"response_format" not in
call_args.kwargs`. **18/18 passing** (17 pre-existing + 1 new).

## 10. Full offline test results

187 passed, 0 failed (`test_v2_1_image_generation_protocol.py` ×16,
`test_v2_1_gemini_image_adapter.py` ×14, `test_v2_1_openai_image_adapter.py` ×18,
`test_v2_1_bakeoff_harness.py` ×9, `test_v2_2a_gemini_response_parsing.py` ×13,
`test_phase18_m5_meme_image_generation.py`, `test_phase18_m6_meme_render.py`,
`test_openai_adapter.py`, `test_settings_phase7.py`). Only pre-existing, unrelated Pillow
deprecation warnings (`Image.getdata`) — baseline noise, not touched.

## 11. Ruff

Clean across every production and test file this phase touched or added.

## 12. mypy

Clean (0 errors, 7 production source files checked).

## 13. Final dry-run proof

Immediately before the live smoke test: `planned_runs: 9`, `network_image_generation_calls: 0`,
`successful_paid_generations: 0`, `actual_cost_usd: 0`. Matched requirement exactly — proceeded.

## 14. prior failed Gemini usage/billing disclosure

Source of truth: `assets/brand/newsroom_visuals/v2_2_bakeoff_live/manifest.json`. **12 prior Gemini
generation attempts (6 original + 6 retries)** — confirmed directly from the manifest's own
`attempts`/`retried` fields, matching the user's stated hypothesis exactly. A `usage` key was
present in the raw HTTP response on all 12, but its contents were never captured (the parsing
failure happened before extraction) — `usage_input_tokens`/`usage_output_tokens`/`actual_cost_usd`
are `null` in that manifest not because usage was absent, but because it was never read.
**Billing impact for those 12 attempts remains UNKNOWN — check the Google AI Studio / Cloud
Billing console directly.** No $0 is asserted or estimated for them here.

## 15. Exact 3 live smoke calls attempted

CASE 1 (`case1_hero_product_iphone`, SHA-256 `c3126a01…`) × 3 models, using the identical canonical
prompt for all 3:
1. `gemini-3.1-flash-image`
2. `gemini-3-pro-image`
3. `gpt-image-2`

**All 3 succeeded on the first attempt.**

## 16. Retries

**None.** `total_attempts: 3`, `retries: []`.

## 17. Output paths

- `assets/brand/newsroom_visuals/v2_2a_protocol_smoke/gemini__gemini-3.1-flash-image.jpg`
- `assets/brand/newsroom_visuals/v2_2a_protocol_smoke/gemini__gemini-3-pro-image.jpg`
- `assets/brand/newsroom_visuals/v2_2a_protocol_smoke/openai__gpt-image-2.png`
- Contact sheet: `assets/brand/newsroom_visuals/v2_2a_protocol_smoke/CONTACT_SHEET_V2_2A_SMOKE.jpg`
- Manifest: `assets/brand/newsroom_visuals/v2_2a_protocol_smoke/manifest.json`

No NNJ overlay, color grading, deterministic branding, or resizing applied to any raw output.

## 18. Output dimensions

| Model | Dimensions | Format |
|---|---|---|
| gemini-3.1-flash-image | 1376×768 | JPEG |
| gemini-3-pro-image | 1376×768 | JPEG |
| gpt-image-2 | 1536×1024 | PNG |

All close-to-16:9 (Gemini: 1.79:1; OpenAI: 1.5:1, its closest supported literal), no fabricated
"exact 1280×720" claimed for either.

## 19. Request IDs

| Model | Request ID |
|---|---|
| gemini-3.1-flash-image | `v1_Chd1eW1RYXVfbEVhcWx2ZElQaU1UdjhBTRIXdXltUWF1X2xFYXFsdmRJUGlNVHY4QU0` |
| gemini-3-pro-image | `v1_ChYwU21RYXFHRExhSFBzZ0x6amFycERnEhYwU21RYXFHRExhSFBzZ0x6amFycERn` |
| gpt-image-2 | `req_3f551239906d44749a8138d1d45eb1ed` |

## 20. Usage / cost metadata

| Model | Input tokens | Output tokens | `actual_cost_usd` | `estimated_cost_usd` (ESTIMATE) |
|---|---|---|---|---|
| gemini-3.1-flash-image | 552 | 1431 | null (not reported by API) | $0.067 |
| gemini-3-pro-image | 552 | 1241 | null (not reported by API) | $0.134 |
| gpt-image-2 | 1798 | 158 | null (not reported by API) | $0.05 |

**Total estimated smoke cost: $0.251** (ESTIMATE only — neither provider's response reports a
dollar figure; billing for these 3 calls should also be checked against each provider's own
console, same as §14's disclosure, out of an abundance of caution).

## 21. Future bake-off qualification

All 3 outputs used the exact canonical source bytes (SHA-256 `c3126a01…`), the exact canonical
prompt, and the same output contract intended for the final bake-off, and no adapter/prompt change
has been made since. **All 3 qualify as valid CASE 1 × {model} results and do not need
regeneration** — reducing the remaining matrix from 9 to 6 cells (Case 2 × 3 models, Case 3 × 3
models).

## 22. Qualitative observation (not a full fidelity ranking)

Visual inspection of all 3 raw outputs: all preserve the source's triple-lens rear camera module,
Apple logo placement/shape, and overall device silhouette/proportions. No obvious
CRITICAL_PRODUCT_MUTATION or MAJOR_VISUAL_MUTATION observed in any of the 3 at this stage — but per
Step 13, this is a smoke-level observation only; full 0-5 rubric scoring and ranking are deferred
until Cases 2 and 3 are available.

## 23. Side-effect audit

| Check | Result |
|---|---|
| Telegram sends | 0 |
| Publications | 0 |
| Production visual invocations | 0 |
| EVENT_RECAP executions caused by this phase | 0 |
| `presentation_director_mode` | `off`, unchanged |
| `automation_worker` restarts | 0 |
| Production pipeline wiring | 0 |
| Commit made | No |

## 24. `automation_worker` final state

`Status=running`, `StartedAt=2026-08-25T20:14:29.785185817Z` (unchanged), `RestartCount=0`.

## 25. `git diff --stat`

```
core/config.py                                     |   5 +
integrations/llm_gateway/image_protocol.py         | 150 ++++++++++++++++++++-
.../llm_gateway/providers/mock_image_adapter.py    |  29 +++-
3 files changed, 175 insertions(+), 9 deletions(-)
```
(Unchanged from before this phase — all V2.1 work; the repaired adapter files are untracked, not
modified.)

## 26. `git status --short`

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
?? integrations/llm_gateway/providers/gemini_image_adapter.py
?? integrations/llm_gateway/providers/openai_image_adapter.py
?? scripts/nnj_v2_2_live_bakeoff_run.py
?? scripts/nnj_v2_2a_protocol_smoke_run.py
?? scripts/nnj_visual_recomposition_bakeoff.py
?? tests/test_v2_1_bakeoff_harness.py
?? tests/test_v2_1_gemini_image_adapter.py
?? tests/test_v2_1_image_generation_protocol.py
?? tests/test_v2_1_openai_image_adapter.py
?? tests/test_v2_2a_gemini_response_parsing.py
```

No commit made.

## Verdict

**A) THREE-MODEL LIVE PROTOCOL SMOKE PASSED — 6 BAKE-OFF CELLS REMAIN**

All 3 models returned a decodable, non-empty, correctly-identified, source-faithful edit on the
first attempt, no retries needed. Both adapter contract bugs from attempt #1 are fixed and
regression-tested. Case 1 × all 3 models can be reused as-is for the final bake-off; Case 2 and
Case 3 (× 3 models each = 6 cells) remain.
