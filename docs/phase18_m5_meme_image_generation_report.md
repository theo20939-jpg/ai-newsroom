# Phase 18 M5 — Meme Image Generation: Implementation Report

Status: complete (engineering, MVP scope). **No live/paid provider call was made or attempted.**
The only wired-up `ImageGenerationGateway` implementation is `MockImageAdapter` — deterministic,
zero-network, zero-cost. `meme_image_generation_mode` defaults to `"off"` and its `Literal` type
does not even contain a `"live"` value yet — see §3.

## 1. What was built

| File | Purpose |
|---|---|
| `integrations/llm_gateway/image_protocol.py` | `ImageGenerationRequest`/`ImageGenerationResponse`/`ImageGenerationGateway` — a new, separate Protocol (see §2) |
| `integrations/llm_gateway/providers/mock_image_adapter.py` | `MockImageAdapter` — deterministic placeholder generator, the only adapter wired up |
| `schemas/meme_image.py` | `MemeImageGenerationResult`, `MemeImageStatus` |
| `services/meme_image_generation.py` | `build_image_prompt()`, `generate_meme_image()` — orchestration, bounded retries |
| `core/config.py` | `meme_image_generation_mode: Literal["off", "dry_run"] = "off"`, `meme_image_max_bytes` |
| `tests/test_phase18_m5_meme_image_generation.py` | 12 tests |

## 2. Why a separate `ImageGenerationGateway`, not an extension of `LLMGateway`

The M0 report (§3.6/§4.2) found no image-generation path exists anywhere in this codebase and
recommended extending the Gateway "along its own seam." Two ways to do that were evaluated:

1. **Add `generate_image()` to the existing `LLMGateway` Protocol** — would require every current
   implementation (`OpenAIAdapter`, the routing/fallback layer, `FakeLLMGateway` — used across
   150+ existing tests) to gain a new method, would need `CapabilityCall.gateway_method`'s closed
   `Literal["generate", "generate_stream", "embed", "classify", "moderate", "rerank"]` widened,
   and touches a Protocol this codebase's own docs describe as governed by a frozen architecture
   contract (Phase 6/7). The shape mismatch is real too: `GenerateRequest` is built entirely
   around `messages`/`tools`/`response_schema` — none of which an image-generation call needs.
2. **A new, parallel Protocol** (chosen) — `ImageGenerationGateway` follows the *exact same
   design discipline* `LLMGateway` established (provider-neutral, no provider SDK type leaks
   through, "the ONLY thing a Capability may call for this modality") without touching a single
   existing file's Protocol surface. Zero risk to the 150+ tests exercising `LLMGateway`, zero
   change to the frozen `build_registry()` signature, zero change to `CapabilityCall.
   gateway_method`.

This is the same architecture pattern applied to a genuinely different call shape — not a new
architecture, and not scope-padding: option 1 was concretely evaluated and rejected for a stated,
verifiable reason (blast radius across already-passing tests + a shape mismatch), matching the
brief's own "если по архитектуре лучше... — так и делай" permission to make a reasoned deviation.

## 3. Why `MemeImageCapability` is not registered in `CapabilityRegistry`

`capabilities.registry.build_registry(gateway, prompt_repository, budget_guard, tool_registry)`'s
signature is documented in that module's own docstring as the fixed boot-order contract (§19 rule
2/3 of the Phase 7 architecture contract). Threading a fifth dependency (`ImageGenerationGateway`)
through it, for a feature no live-running workflow reaches yet (MEME_GENERATION has no `meme_image`
step in `workflows/definitions/meme_generation.py` as of M5 — see §6), would be exactly the kind
of unnecessary architecture change the operating rules warn against. Image generation is instead a
plain orchestration function (`generate_meme_image()`), directly analogous to `services/
telegram_notifier.py::send_editorial_card()` — a "service function with a directly-inspectable
outcome object," an established pattern in this codebase that was never built on the Capability
Framework either. Wiring `meme_image` into the workflow chain (and reassessing whether a Capability
Framework seam extension is then justified) is deferred to whichever milestone actually needs it.

## 4. MVP scope decisions (per the brief's own M5 requirements)

- **One visual format**: 1024×1024 square PNG only — `ImageGenerationRequest.size` is a
  single-value `Literal`, not an open string, so nothing downstream can accidentally request an
  unsupported size.
- **No text baked into the image**: `build_image_prompt()` builds the prompt from `MemeConcept.
  visual_scene`/`characters_objects` only — never the punchline or copy — and explicitly instructs
  "no text, no letters, no words." M6 (Rendering) is the only place overlay text is ever added,
  per the brief's own stated preference ("генерировать изображение без текста... это
  предпочтительно").
- **Bounded retries, not unlimited regeneration**: `_MAX_GENERATION_ATTEMPTS = 2` inside one
  `generate_meme_image()` call (tested: `test_generation_failure_after_bounded_attempts_returns_failed`
  asserts exactly 2 attempts, never more). Regeneration *across* separate human-triggered attempts
  (a future M8 "regenerate image" button) is a distinct, caller-tracked concern —
  `MemeCandidate.image_regeneration_count` (already reserved in M2's migration) — not something
  this function itself loops on.
- **Cost visibility**: every result carries `cost_usd` (currently always `"0"`, the mock
  provider's real cost) and `provider`/`model_used` — the fields a future real-provider cost
  formula would populate are already present and exercised by tests, just always zero today.
- **Default off, dry-run safe**: `meme_image_generation_mode` defaults to `"off"`; the only other
  value, `"dry_run"`, exercises the mock adapter, never a network call. No `"live"` value exists
  in the `Literal` type at all — a future authorized milestone must *add* that value before any
  code path could even attempt to select it, which is a stronger guarantee than a runtime check
  that could be flipped by an environment variable alone.

## 5. Testing

12/12 tests pass: `build_image_prompt()` includes the visual scene and objects, excludes the
punchline, and instructs against on-image text; `MockImageAdapter` is deterministic per-prompt,
differs across prompts, produces a valid decodable 1024×1024 PNG, and reports `usage.units=1,
unit_type="image"`; `generate_meme_image(mode="off")` makes zero gateway calls (proven with a
gateway that raises `AssertionError` if ever invoked); `mode="dry_run"` generates, stores via a
real (temp-directory) `LocalImageStorage`, and returns a result with a verified-existing
`storage_key`; a gateway that always raises exhausts exactly `_MAX_GENERATION_ATTEMPTS` (2) and
returns `FAILED` with an `error_code`, never raising past this function; a gateway that fails once
then succeeds proves the retry path actually recovers; a gateway returning malformed (non-image)
bytes is caught by Pillow decode/verify and reported as `FAILED`, never an unhandled exception;
and regenerating the identical concept twice proves storage idempotency (same content → same
key, `LocalImageStorage`'s own existing precedent, exercised here for the first time with
*generated*, not fetched, bytes).

Regression: full Phase 18 suite — **82/82 pass** across all five milestones together.
`python -m pytest --collect-only -q` — **2225 tests collected** (2213 + 12 new), 0 collection
errors.

## 6. What is explicitly NOT done in M5 (disclosed, not oversights)

- **No real, paid provider adapter exists.** Per the operating rules, this requires separate
  human authorization before it is even built against a real API key, let alone called. Building
  a real `OpenAIImageAdapter`-equivalent now, never to be exercised, was considered and rejected
  as premature — the request/response contract (`ImageGenerationRequest`/`Response`) is already
  stable and provider-agnostic, so adding a real adapter later is a contained, additive change
  that does not require touching this milestone's code.
- **`meme_image` is not yet a step in `workflows/definitions/meme_generation.py`.** Wiring it in
  requires deciding how the workflow step (which returns a `CapabilityResult`-shaped JSON
  structured-output for `WorkflowStepResult.result`) should represent an outcome whose real
  payload (image bytes) must never enter that JSON — this is exactly M6's own concern (the
  renderer is the natural place to decide what a workflow step "result" for an image artifact
  should even look like, since M6 produces the actual, final asset). Deferred there rather than
  guessed at here.
- **`MemeCandidateService` has no image-stage writer method yet** — same deferral pattern as
  M2/M3/M4.

## 7. Next milestone

M6 (Meme Rendering / Text Overlay) — takes `MemeImageGenerationResult.storage_key` +
`MemeCopy` and produces the final, text-overlaid asset. This is also the natural point to decide
how (or whether) `meme_image`/`meme_render` become real MEME_GENERATION workflow steps.
