# Phase 18 M4 — Meme Copywriting: Implementation Report

Status: complete. `WorkflowType.MEME_GENERATION` is now registered in `WorkflowRegistry` (a
change from M2's "declared but unregistered" state — see §2). No automatic caller creates a
MEME_GENERATION task, so this remains inert in production; no live LLM call has been made.

## 1. What was built

| File | Purpose |
|---|---|
| `schemas/meme_copy.py` | `MemeCopy` — frozen contract for top/bottom text, punchline, caption, editor explanation, alt text; length ceilings + URL-in-on-image-text rejection enforced at the schema level |
| `prompts/meme_copywriting/v1.yaml` | Governed system/rules/output_schema |
| `capabilities/meme_copywriting_capability.py` | `MemeCopywritingCapability` — reads `step_results["meme_concept"]`, optionally folds in `editorial_brief`'s `why_it_matters` when present |
| `capabilities/capability_mapping.py` | `"meme_copywriting"` → `AICapability.COPYWRITING` (reused, zero new enum value) |
| `capabilities/registry.py` | `MemeCopywritingCapability` registered |
| `workflows/definitions/meme_generation.py` | Step list extended: research → intelligence → meme_concept → meme_copywriting |
| `workflows/registry.py` | `WorkflowType.MEME_GENERATION` now registered |
| `tests/test_meme_copywriting_capability.py` | 7 tests |
| `tests/test_phase18_m4_meme_copy_schema.py` | 9 tests |
| `tests/test_phase18_m2_meme_concept_schema_and_registry.py` | 2 tests updated (registration status, step list) to match the now-registered workflow |

## 2. Design decisions and why

- **Mobile-readability and no-URL-on-image are schema-enforced, not prompt-only.** `MemeCopy`
  caps `top_text`/`bottom_text` at 80 chars, `punchline_short` at 120, and rejects any URL inside
  `top_text`/`bottom_text`/`punchline_short` via a `field_validator` — a model that ignores the
  prompt's own instructions still cannot produce a `MemeCopy` object with a URL baked into the
  rendered image. `telegram_caption` (which lives outside the image, in the Telegram message
  text) is explicitly exempt — a source link there is normal and useful, tested directly
  (`test_url_in_telegram_caption_is_allowed`).
- **Separate capability from `meme_concept`, not merged** — per the M0 report's own recommended
  order (§10 point 4): "one capability per distinct judgment" is this codebase's existing norm
  (research/intelligence/copywriting/quality are four separate calls in CONTENT_GENERATION
  already), so `meme_copywriting` follows the same shape rather than being an outlier.
- **`"meme_copywriting"` maps to `AICapability.COPYWRITING`, not `CREATIVE`** — unlike
  `meme_concept` (genuinely open-ended ideation), this step is literally copywriting; reusing the
  semantically-correct existing enum value keeps `AIExecution` cost rows meaningfully labeled
  without needing a new value.
- **Phase 17 editorial intelligence is reused as input, never duplicated** (brief's own explicit
  M4 requirement): `_format_editorial_intelligence_context()` reads
  `step_results["intelligence"].get("editorial_brief", {}).get("why_it_matters")` when present —
  this key is populated by Phase 17 M1's own `_attach_editorial_brief()` hook, which already runs
  for *any* workflow whose step is literally named `"intelligence"` (the hook is gated on
  `step.capability == "intelligence"`, not on which `WorkflowType` the step belongs to) — so
  turning on `editorial_brief_mode="shadow"` benefits MEME_GENERATION for free, with zero new
  code in that hook. Tested directly (`test_editorial_brief_summary_included_when_present`).
  Absent (the default, since `editorial_brief_mode` defaults to `"off"`), the capability degrades
  gracefully exactly like every sibling capability's own "did not run" handling.
- **`WorkflowType.MEME_GENERATION` is now registered.** M2/M3's reports both flagged this as "to
  be reassessed once M4 lands" — research → intelligence → meme_concept → meme_copywriting is a
  coherent, independently useful chain (a complete, safety/originality-assessed, human-readable
  text meme package, even before an image exists). Registering only makes `WorkflowRunner.run()`
  *able* to execute this workflow if some caller explicitly creates a task for it — no such caller
  exists (no script or worker creates a MEME_GENERATION task automatically), so this change has
  zero production behavior effect on its own. Verified via `test_registry_consistency.py`/
  `test_workflow_registry.py` (both pass unmodified) and a new
  `test_workflow_type_meme_generation_registered_as_of_m4` test.

## 3. Testing

- **`tests/test_meme_copywriting_capability.py`** (7/7): full-shape execution proving the
  concept's own punchline/visual_scene reach the built prompt; graceful degradation when
  `meme_concept` step results are absent; the editorial-intelligence reuse path; validation
  failure raising `ValidationCapabilityError`; constructor signature; AST-based non-coupling
  check (no import of `meme_concept_capability`); and a real-prompt-file ↔ schema consistency
  check (same discipline as M2's equivalent test).
- **`tests/test_phase18_m4_meme_copy_schema.py`** (9/9): frozen model; `bottom_text`/
  `editor_explanation` may be `None`; a URL in `top_text`/`bottom_text`/`punchline_short` is
  rejected (parametrized over all three fields) while the same URL in `telegram_caption` is
  accepted; an overlong `top_text` is rejected; unknown fields rejected; capability-mapping
  correctness.
- **Bug caught during testing (not a defect, a real YAML gotcha)**: the first draft of
  `prompts/meme_copywriting/v1.yaml` had a rule line reading `"...technology-news audience:
  informed, ..."` — the `: ` inside an unquoted, line-wrapped YAML list-item scalar caused a
  `yaml.scanner.ScannerError` at load time (a colon-space sequence inside a plain scalar is a
  reserved indicator in YAML). Fixed by rewording to avoid the colon; a regression test
  (`test_real_v1_prompt_file_loads_and_matches_the_meme_copy_schema`) now loads the real file, so
  a similar future YAML mistake fails a test immediately rather than only at runtime.
- **Full Phase 18 regression**: `python -m pytest tests/ -k "phase18 or meme"` — **70/70 pass**
  across all four milestones' test files together. `tests/test_capability_registry.py` +
  `tests/test_registry_consistency.py` + `tests/test_workflow_registry.py` — **20/20 pass**
  unmodified, confirming `MEME_GENERATION`'s registration didn't disturb `NEWS_ANALYSIS`/
  `CONTENT_GENERATION`. `python -m pytest --collect-only -q` — **2213 tests collected** (2197 +
  16 new: 7+9), 0 collection errors.
- **Not run this session** (disclosed, unchanged constraint): any live LLM call, and any
  DB-backed `WorkflowRunner.run()` execution of the real MEME_GENERATION chain — the local
  Postgres/Redis stack remains unavailable.

## 4. Risks / limitations carried forward

- The prompt has never produced a real model response — its request/response shape is proven
  correct against `FakeLLMGateway` only, same caveat as M2's `meme_concept`.
- `MemeCopy`'s length ceilings (80/120/300/200 chars) are v1 estimates for "mobile-readable,"
  not measured against a real rendered image yet — M6 (rendering) is where actual pixel-level
  readability gets validated; these ceilings may need adjustment once real overlay rendering
  exists.
- No `MemeCandidateService` writer method for copy data exists yet — mirrors M2/M3's own
  deferral; persistence wiring is still bundled into the still-open orchestration question.

## 5. Next milestone

M5 (Meme Image Generation) — the milestone requiring the most novel engineering (per `docs/
phase18_m0_meme_discovery_report.md` §3.6/§4.2: no image-generation path exists anywhere in this
codebase yet). Ships fully wired but default off/dry-run; no live/paid provider call without
separate human authorization.
