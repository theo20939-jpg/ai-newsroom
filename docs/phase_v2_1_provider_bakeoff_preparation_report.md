# Phase V2.1 — Provider-Neutral Image Edit Protocol & Three-Model Bake-Off Preparation

Final report. Canonical HEAD unchanged: `f8a604b5d4e113e53b96a2655ec38644eeafbef0`. Nothing in
this phase has been committed. No live/paid provider call has been made anywhere in this phase.

## 1. Architecture decision

Extended the existing `ImageGenerationGateway` / `ImageGenerationRequest` / `ImageGenerationResponse`
(`integrations/llm_gateway/image_protocol.py`) in place — no second/parallel image-generation
subsystem was created. The persistence/retry/fail-open pattern established by
`services/meme_image_generation.py` (Phase 18 M5) remains canonical and untouched.

## 2. The blocker from Phase V2 and how it was resolved

V2's verdict B found `ImageGenerationRequest` supported only `prompt: str`, with no way to attach a
source/reference image. This phase adds, backwards-compatibly:
- `operation: ImageGenerationOperation` (`TEXT_TO_IMAGE` default / `IMAGE_EDIT`)
- `reference_images: tuple[ReferenceImage, ...] = ()`
- `target_aspect_ratio` / `target_width` / `target_height` (optional output hints)
- Removed the old `size: Literal["1024x1024"]` field — proven dead by a full-repo grep (never read,
  never passed explicitly by any of the three existing call sites) before removal, and confirmed
  post-removal by the full pre-existing `test_phase18_m5_meme_image_generation.py` +
  `test_phase18_m6_meme_render.py` suites passing unmodified (25/25).

Every pre-existing construction site (`ImageGenerationRequest(prompt=...)`) still works unchanged.

## 3. Model ID / API contract verification (dated 2026-08-27)

- `gemini-3.1-flash-image` / `gemini-3-pro-image`: confirmed current (their `-preview` siblings are
  deprecated, shutting down 2026-06-25) via WebFetch of ai.google.dev/deepmind.google docs, three
  independent times. Documented only through Google's newer Interactions API
  (`POST https://generativelanguage.googleapis.com/v1beta/interactions`, `x-goog-api-key` header).
  **Disclosed uncertainty**: no verbatim raw JSON response example was found in any fetch, so the
  exact response key casing is inferred from the SDK attribute name (`interaction.output_image.data`)
  and the request's own snake_case convention — not independently confirmed byte-for-byte. The
  adapter defensively accepts both snake_case and camelCase.
- `gpt-image-2`: confirmed current (launched 2026-04-21) via WebFetch + WebSearch corroboration.
  Exact parameter names and response shape were verified by directly introspecting the installed
  `openai==2.45.0` package (`inspect.signature`, Pydantic model fields) — the strongest verification
  available short of a live call. `size` is a closed Literal with no exact 16:9/1280x720 option;
  `1536x1024` is used as the closest supported landscape size.

No requested model was found unavailable; none was silently substituted.

## 4. Adapters

- `integrations/llm_gateway/providers/gemini_image_adapter.py` — **one shared class**,
  `GeminiImageAdapter(model_id=...)`, used for both Gemini models (identical API contract, only the
  `model` field differs) — not two duplicated adapters.
- `integrations/llm_gateway/providers/openai_image_adapter.py` — separate file, `client.images.*`
  only (provider isolation: `openai_adapter.py` remains `client.responses.create` only; neither
  file imports the other). `TEXT_TO_IMAGE` via `gpt-image-2` is explicitly rejected (not silently
  downgraded) since it was not verified in this phase — a deliberate asymmetry vs. the Gemini
  adapter, disclosed in the adapter's own docstring.
- Both implement `ImageAdapterCapabilities` (`supports_text_to_image`, `supports_image_edit`,
  `max_reference_images`, `supports_aspect_ratio_control`) as a `CAPABILITIES` class attribute —
  the smallest capability descriptor, not a new plugin/registry framework.
- `MockImageAdapter` updated: `CAPABILITIES.supports_image_edit = False`, and
  `generate_image()` raises `NotImplementedError` for `IMAGE_EDIT` rather than silently downgrading
  to `TEXT_TO_IMAGE`.
- No new SDK dependency added. Gemini adapter uses the already-present `httpx`; OpenAI adapter uses
  the already-present `openai` package.

## 5. Credential audit (presence only, never a value)

| Key | Status |
|---|---|
| `OPENAI_API_KEY` | PRESENT |
| `GEMINI_API_KEY` | ABSENT |

`gemini_api_key: SecretStr | None` added to `core/config.py`, mirroring `openai_api_key` — unused
by any existing code path before this phase.

## 6. Canonical provider-neutral prompt

`scripts/nnj_visual_recomposition_bakeoff.py::build_recomposition_prompt()` — one fixed string,
transcribed from `docs/nnj_source_faithful_editorial_visual_recomposition_v1.md` §12, sent
byte-identical to all three models across all nine planned runs. A plain, versionless function
mirroring `services/meme_image_generation.py::build_image_prompt()`'s own shape, per that document's
own instruction for this exact future step.

## 7. Fair output-size contract

| Model | Requested | Actual native support |
|---|---|---|
| `gemini-3.1-flash-image` / `gemini-3-pro-image` | 16:9 (~1280×720) | `response_format.aspect_ratio` hint sent; exact enforcement unconfirmed (Interactions API docs did not show a verbatim size-negotiation response) |
| `gpt-image-2` | 16:9 (~1280×720) | No exact match in the closed `size` Literal; closest is `1536x1024` |

Neither is pretended to natively hit 1280×720 — both mismatches are disclosed, not hidden.

## 8. Bake-off harness

`scripts/nnj_visual_recomposition_bakeoff.py` — standalone, not imported by `worker/content_cycle.py`,
`services/presentation_director.py`, `services/brand_renderer.py`, Telegram notifiers, or EVENT_RECAP.
Defaults to dry run; `--live` (never passed in this phase), `--output-dir`,
`--max-successful-generations` (default 9), `--max-cost-usd` are all supported.

## 9. Source images (no human portrait)

`assets/brand/newsroom_visuals/v2_1_bakeoff_sources/` (+ `provenance.json` with rationale/SHA-256):

| Case | File | SHA-256 (short) | Dimensions |
|---|---|---|---|
| 1 — hero product/iPhone | `case1_hero_product_iphone.jpg` | `c3126a01…` | 1122×1402 |
| 2 — second gadget, geometry/detail | `case2_gadget_geometry_detail.jpg` | `83761c78…` | 1920×1005 |
| 3 — bright/saturated promotional | `case3_bright_promotional_scene.jpg` | `36ccc2bb…` | 1122×1402 |

Case 1 and 3 reused unchanged from the V2 design-phase local proof; Case 2 selected fresh from the
existing local (docker-cp, read-only, no-network) photo pool. A portrait candidate in that same pool
was explicitly excluded per rule.

## 10. The 3×3 = 9-run matrix (prepared, never executed)

All 9 `(case, model)` pairs — see §12 manifest below. Every run currently has `executed: false`.

## 11. Evaluation rubric & fidelity flags (schema only, not yet populated)

`EvaluationRubric` (0-5 each): Factual Product Fidelity, Composition Improvement, NNJ Safe-Zone
Quality, Photorealism/Artifacts, Prompt Adherence — plus `EditStrength` (minimal/moderate/aggressive)
and `FidelityFailureFlag` (none / minor / major / critical) as a **separate** field from the numeric
score. All `None`/`none` until a human reviewer scores a real output — never auto-filled.

## 12. No LLM image judge

`BasicAutomatedChecks` performs only mechanical checks on any real output: decodability, MIME,
dimensions, SHA-256, byte-identity-to-source. No model is used to score or compare outputs.

## 13. Cost estimate (ESTIMATE only, not a quote)

| Model | Est. $/image | ×3 cases |
|---|---|---|
| `gemini-3.1-flash-image` | $0.067 | $0.201 |
| `gemini-3-pro-image` | $0.134 | $0.402 |
| `gpt-image-2` | $0.05 (ceiling) | $0.15 |
| **Total (9 runs)** | | **$0.753** |

Sourced from each adapter's own dated docstring citation; distinct from any future
`actual_cost_usd`, which is only ever populated from a real provider response.

## 14. Tests

47 new tests, all passing:
- `tests/test_v2_1_image_generation_protocol.py` — 16 (legacy compat, validation, Mock non-support)
- `tests/test_v2_1_gemini_image_adapter.py` — 14 (both models, request/response mapping, fail-open, security)
- `tests/test_v2_1_openai_image_adapter.py` — 17 (request/response mapping, fail-open, TEXT_TO_IMAGE rejection, security)
- `tests/test_v2_1_bakeoff_harness.py` — 9 (matrix shape, prompt determinism, credential audit, dry-run zero-cost proof)

Plus the full pre-existing `test_phase18_m5_meme_image_generation.py` (12), `test_phase18_m6_meme_render.py`
(13), and `test_openai_adapter.py` (37) suites re-run unmodified: all passing. **123/123 total.**

## 15. Dry-run execution proof

`assets/brand/newsroom_visuals/v2_provider_bakeoff_dry_run/manifest.json`:
`planned_runs: 9`, `network_image_generation_calls: 0`, `successful_paid_generations: 0`,
`actual_cost_usd: 0`, `estimated_max_cost_usd: 0.753`.

## 16. Non-wiring confirmation

`git status --short` shows changes confined to: `core/config.py`,
`integrations/llm_gateway/image_protocol.py`, `integrations/llm_gateway/providers/mock_image_adapter.py`
(modified); two new adapter files, the harness script, four new test files, and the new
`assets/brand/newsroom_visuals/` sources/manifest/docs (untracked additions). Zero changes to
`worker/content_cycle.py`, `services/presentation_director.py`, `services/brand_renderer.py`, or any
Telegram notifier.

## 17. Ruff / mypy

`ruff check` and `mypy` both clean (zero errors) across every production and test file this phase
touched or added.

## 18. Side-effect audit

- Paid provider calls: 0
- Gemini/OpenAI image generations: 0
- Telegram sends: 0
- Publications: 0
- Production visual/EVENT_RECAP invocations: 0
- `ai_newsroom_automation_worker`: RestartCount 0, StartedAt unchanged (2026-08-25T20:14:29Z) — never touched
- `presentation_director_mode`: unchanged (not read or written by any file this phase touched)
- No commit made

## Verdict

**READY FOR LIVE BAKE-OFF — architecture extended, both adapters implemented and fully tested against
official/introspected API contracts, harness built and dry-run-proven (9 planned, 0 executed, $0
actual cost). Nothing has been committed and no live/paid call has been made. Waiting for explicit,
separate user authorization before running `python scripts/nnj_visual_recomposition_bakeoff.py --live`.**
